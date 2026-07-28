"""Syrupy extension that serializes and compares matplotlib figures.

`MplFigureExtension` subclasses syrupy's `SingleFileSnapshotExtension` so
each snapshot is a standalone `.png` under `__snapshots__/<module_stem>/`.

Per-assertion state (`SnapshotParams`, node id, snapshot stem) is stamped
onto the extension instance by `MplSnapshotAssertion._assert` before
`matches()` runs — syrupy's `matches(*, serialized_data, snapshot_data)`
signature does not thread that context through otherwise. Session-wide
state (`_mpl_collector`, `_mpl_update_snapshots`) is bound on the class by
`Plugin.bind_extension_class` at fixture setup (not `pytest_configure`, so
the entry-point module never imports this matplotlib-heavy module). The
diagnostic-artifact directory rides on `collector.results_root`.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from matplotlib.figure import Figure
from matplotlib.testing.decorators import remove_ticks_and_titles
from syrupy.data import SnapshotCollections
from syrupy.extensions.single_file import SingleFileSnapshotExtension
from syrupy.extensions.single_file import WriteMode

from ._comparison import run_comparison
from ._config import VARIANT_ROOT_DIRNAME
from ._config import VARIANT_TAG_PATTERN
from ._figures import save_figure_to_bytes
from ._reporting import ResultRecord
from ._types import ImageMatchStatus
from ._types import ImageResult
from ._types import is_passing

if TYPE_CHECKING:
    from syrupy.location import PyTestLocation

    from ._params import SnapshotParams
    from ._reporting import ResultCollector


class MplFigureExtension(SingleFileSnapshotExtension):
    """One `.png` per snapshot under `__snapshots__/<module_stem>/`.

    Per-environment variants of those baselines live under
    `__snapshots_variants__/<tag>/<module_stem>/`, and this class handles them around
    syrupy rather than through it: `get_location` is left reporting the
    canonical path in every mode, `read_snapshot_data_from_location` swaps in
    the variant's bytes, and `_decide_variant_write` writes the variant file
    itself. Syrupy counts the location it hands out as the snapshot the run
    used and reports every other file under `__snapshots__/` as unused — which
    fails the session — then deletes it on the next `--snapshot-update`. Any
    plain `snapshot` fixture in the directory arms that sweep, since syrupy's
    default extension discovers the whole tree, so naming anything but the
    canonical baseline surrendered the baseline itself.

    Per-assertion state is stamped by `MplSnapshotAssertion._assert` before
    `matches()` runs. Reset between calls so nothing leaks.
    """

    file_extension = "png"
    _write_mode = WriteMode.BINARY

    _mpl_params: SnapshotParams | None = None
    """Effective per-assertion params; stamped by the assertion."""

    _mpl_collector: ResultCollector | None = None
    """Shared report collector; bound by `Plugin.bind_extension_class`."""

    _mpl_rootpath: Path | None = None
    """Pytest rootpath; bound by `Plugin.bind_extension_class`. Used to namespace
    artifact paths under `figure-report/` so xdist workers running tests in
    different modules with overlapping test names don't clobber each other."""

    _mpl_update_snapshots: bool = False
    """`True` when `--snapshot-update` is active; bound by
    `Plugin.bind_extension_class`."""

    _mpl_keep_match_artifacts: bool = False
    """`True` when a report format is requested; bound by
    `Plugin.bind_extension_class`. When `False`, MATCH comparisons leave no
    files in `figure-report/`."""

    _mpl_nodeid: str | None = None
    """Full pytest node id; the `ResultRecord` key is this plus `::<stem>`."""

    _mpl_test_filepath: str | None = None
    """Absolute path of the current test's source file; stamped by the assertion."""

    _mpl_last_stem: str | None = None
    """Filename stem of the current snapshot; stamped by the assertion."""

    _mpl_last_failure_message: str | None = None
    """Failure message for the most recent `matches()` call, or `None`."""

    _mpl_variant: str = ""
    """Baseline-variant tag for this environment (`mpl-3.10`), or `""` when
    variant lookup is off; bound by `Plugin.bind_extension_class`."""

    _mpl_write_variants: bool = False
    """`True` under `--snapshot-update --snapshot-matplotlib-pin-variant`;
    bound by `Plugin.bind_extension_class`."""

    _mpl_canonical_location: str | None = None
    """Canonical baseline path for the snapshot being read, set by
    `read_snapshot_data_from_location` when it is asked for a variant."""

    _mpl_snapshot_dir: str | None = None
    """Directory of the baseline the current assertion read, set by
    `read_snapshot_data_from_location`. Tells `matches()` which snapshot
    directory a rewrite happened in, so the stale-variant warning names only
    the tags sitting next to a baseline this run actually changed."""

    _mpl_baseline_variant: str | None = None
    """Tag of the variant actually served to `matches()`, or `None` when the
    canonical baseline was used."""

    _mpl_canonical_missing: bool = False
    """`True` when the canonical baseline behind the snapshot being read is
    missing — variant-writing mode has nothing to compare against, and a
    comparison run is about to pass off a variant nothing can regenerate.
    Makes `serialize()` refuse the snapshot."""

    _mpl_scanned_dirs: set[str] = set()  # ruff: ignore[mutable-class-default]
    """Snapshot directories already scanned for variant subdirectories.
    Class-level so the scan happens once per directory, not once per
    snapshot; cleared by `pytest_unconfigure`."""

    # ── Baseline location: canonical is the snapshot, variants answer for it ──

    def read_snapshot_data_from_location(
        self, *, snapshot_location: str, snapshot_name: str, session_id: str
    ) -> Any:
        """Read the baseline, preferring the variant that answers for it.

        A plain `--snapshot-update` is the exception: it reads and rewrites the
        canonical baseline even where a variant exists, so a re-baseline never
        consults, and never lands in, a variant file.

        Args:
            snapshot_location: Canonical path from `get_location`.
            snapshot_name: Snapshot stem (unused by the single-file base).
            session_id: Syrupy session id.

        Returns:
            The variant bytes when one answers for this environment, else the
            canonical bytes, else `None`.
        """
        self._mpl_canonical_location = snapshot_location
        self._mpl_baseline_variant = None
        self._mpl_canonical_missing = False
        self._mpl_snapshot_dir = str(Path(snapshot_location).parent)

        canonical_update = self._mpl_update_snapshots and not self._mpl_write_variants
        variant = self._build_variant_location(snapshot_location)
        if variant is not None and not canonical_update and variant.exists():
            data = super().read_snapshot_data_from_location(
                snapshot_location=str(variant),
                snapshot_name=snapshot_name,
                session_id=session_id,
            )
            if data is not None:  # pragma: no branch
                self._mpl_baseline_variant = self._mpl_variant
                # A successful variant read must not hide a deleted canonical
                # baseline. A comparison run would pass off the variant
                # silently, and a variant-writing run would keep it (or pass it
                # on byte equality), leaving a baseline that only shadows and
                # that nothing can regenerate: pinning a variant compares it
                # against a canonical baseline.
                self._mpl_canonical_missing = not Path(snapshot_location).exists()
                return data

        data = super().read_snapshot_data_from_location(
            snapshot_location=snapshot_location,
            snapshot_name=snapshot_name,
            session_id=session_id,
        )
        # Nothing to pin against, and nothing syrupy may write in this mode:
        # `serialize()` refuses the snapshot rather than let a variant-writing
        # run create the canonical baseline it is supposed to compare with.
        if data is None and self._mpl_write_variants:
            self._mpl_canonical_missing = True
        return data

    def discover_snapshots(
        self,
        *,
        test_location: PyTestLocation,
        ignore_extensions: list[str] | None = None,
    ) -> SnapshotCollections:
        """Return the snapshots syrupy may report as unused, and only those.

        Syrupy's own discovery, minus anything sitting below the module
        directory: a legacy nested tag directory (variants lived under
        `__snapshots__/<module>/` before) or whatever else a user parked there
        is not this run's to report. Variants need no filtering — they live
        outside the tree syrupy walks — and no discovery either, since this
        plugin writes and prunes them itself.

        Args:
            test_location: Syrupy's wrapper around the current pytest node.
            ignore_extensions: Extensions syrupy was told to skip.

        Returns:
            The snapshot collections this run maintains.
        """
        discovered = super().discover_snapshots(
            test_location=test_location, ignore_extensions=ignore_extensions
        )
        module_dir = Path(self.dirname(test_location=test_location))

        filtered = SnapshotCollections()
        for collection in discovered:
            if Path(collection.location).parent != module_dir:
                continue
            filtered.add(collection)
        return filtered

    @classmethod
    def _build_variant_root(cls, module_dir: Path) -> Path:
        """Return the directory tree holding every variant beside the tests.

        `VARIANT_ROOT_DIRNAME` sits next to the snapshot directory rather than
        inside it, because everything under `__snapshots__/` belongs to
        syrupy's own bookkeeping: its default extension discovers that whole
        tree, and a file the run did not use is reported as an unused snapshot
        — which fails the session — and deleted by the next
        `--snapshot-update`. A variant describing another environment is
        unused by definition, so nesting it there handed other environments'
        baselines to the first `--snapshot-update` anyone ran.

        Args:
            module_dir: The `<snapshot dir>/<module_stem>` directory.

        Returns:
            The variant root beside the snapshot directory.
        """
        # `snapshot_dirname` is syrupy's `--snapshot-dirname`, and may itself
        # be a nested path; its depth is what makes the test file's own
        # directory reachable from the module directory.
        depth = len(Path(cls.snapshot_dirname).parts)
        return module_dir.parents[depth] / VARIANT_ROOT_DIRNAME

    @classmethod
    def _build_variant_dir(cls, module_dir: Path) -> Path:
        """Return the directory holding this environment's variants for a module.

        Args:
            module_dir: The `<snapshot dir>/<module_stem>` directory.

        Returns:
            `<variant root>/<tag>/<module_stem>`.
        """
        return cls._build_variant_root(module_dir) / cls._mpl_variant / module_dir.name

    @classmethod
    def _build_variant_location(cls, canonical: str) -> Path | None:
        """Return the variant path matching *canonical*.

        Args:
            canonical: Canonical baseline path.

        Returns:
            The path under the tag directory, or `None` when no variant tag
            is active.
        """
        if not cls._mpl_variant:
            return None
        path = Path(canonical)
        return cls._build_variant_dir(path.parent) / path.name

    @classmethod
    def _note_variant_dirs(cls, snapshot_dir: Path) -> None:
        """Record the variant directories holding baselines for this module.

        Feeds the warning a canonical re-baseline emits: the plugin cannot
        tell whether those variants still describe their environments, having
        never rendered under them.

        A directory only counts when it is shaped like a variant tag *and*
        holds a baseline for this module — a stray `archive/` must not be
        named in the warning, neither must a tag directory that only carries
        other modules' variants, and neither must the empty
        `<tag>/<module>/` a pin run leaves behind when it deletes the last
        variant it contained.

        Args:
            snapshot_dir: The `<snapshot dir>/<module_stem>` directory.
        """
        collector = cls._mpl_collector
        if collector is None:  # pragma: no cover
            return
        key = str(snapshot_dir)
        if key in cls._mpl_scanned_dirs:
            return
        cls._mpl_scanned_dirs.add(key)
        try:
            entries = list(cls._build_variant_root(snapshot_dir).iterdir())
        except OSError:
            # No variant root at all: the common case for a suite that never
            # pinned anything.
            return
        module = snapshot_dir.name
        for entry in entries:
            if (
                entry.is_dir()
                and VARIANT_TAG_PATTERN.fullmatch(entry.name)
                and any((entry / module).glob(f"*.{cls.file_extension}"))
            ):
                collector.note_variant_dir(entry.name)

    def serialize(
        self,
        data: Any,
        *,
        exclude: Any = None,
        include: Any = None,
        matcher: Any = None,
    ) -> bytes:
        """Render a `Figure` to deterministic PNG bytes.

        Under `remove_text`, *data* is mutated in place — `remove_ticks_and_titles`
        strips the figure itself, not a copy, matching `image_comparison`. The
        caller keeps a stripped figure after the assertion returns.

        Args:
            data: The operand passed to `==`. Must be a `matplotlib.figure.Figure`.
            exclude: Unused (syrupy signature).
            include: Unused (syrupy signature).
            matcher: Unused (syrupy signature).

        Returns:
            Raw PNG bytes ready for on-disk comparison.

        Raises:
            TypeError: If *data* is not a `matplotlib.figure.Figure`.
            RuntimeError: If the snapshot has no canonical baseline — nothing
                for variant-writing mode to compare against, and a variant a
                comparison run must not pass off silently.
        """
        if not isinstance(data, Figure):
            msg = f"snapshot comparison expected a Figure, got {type(data).__name__}."
            raise TypeError(msg)
        params, stem = self._stamped_state()
        # Raising is what stops the write: syrupy queues a snapshot write for
        # any failed assertion in update mode, and only an exception escaping
        # `_assert`'s try block skips it. Refusing here also keeps the variant
        # subdirectory from being created at all, and runs before the
        # GENERATED record below, so a refused snapshot is not counted as
        # created. `serialize()` is the hook that carries it in a comparison
        # run too: an exception from `matches()` is swallowed by syrupy's
        # `_assert`, which would turn the refusal into a pixel mismatch.
        if self._mpl_canonical_missing:
            raise RuntimeError(
                _build_variant_only_message(stem, self._current_variant_path())
            )
        fig: Figure = data
        if params.remove_text:
            remove_ticks_and_titles(fig)

        png_bytes = save_figure_to_bytes(
            fig, self.file_extension, params.savefig_kwargs
        )

        # Update mode: ``matches()`` is not called for brand-new baselines
        # (syrupy writes the snapshot directly). Emit a "created" record
        # here so the terminal summary can count it — after serialization,
        # so a savefig failure isn't counted as a created baseline.
        if self._mpl_update_snapshots:
            self._record(stem, _GENERATED_RESULT)

        return png_bytes

    def matches(self, *, serialized_data: Any, snapshot_data: Any) -> bool:
        """Run pixel comparison against the stored baseline.

        Propagates the `RuntimeError` raised by `_stamped_state()` and
        `_require_artifact_dir()` when the assertion did not stamp its
        per-call state or a collector carrying `results_root`.

        Args:
            serialized_data: Bytes produced by `serialize()`.
            snapshot_data: Bytes read from the on-disk baseline, or `None`.

        Returns:
            `True` when the comparison passes.
        """
        params, stem = self._stamped_state()
        test_bytes = _coerce_bytes(serialized_data)
        baseline_bytes = (
            _coerce_bytes(snapshot_data) if snapshot_data is not None else None
        )

        if self._mpl_write_variants:
            return self._decide_variant_write(params, stem, test_bytes)

        if self._mpl_update_snapshots:
            self._mpl_last_failure_message = None
            unchanged = test_bytes == baseline_bytes
            # `serialize()` optimistically recorded a GENERATED result — the
            # only signal available for a brand-new baseline, where syrupy
            # never calls `matches()`. When a baseline already exists we know
            # more: an unchanged figure is a MATCH, not a creation. Overwrite
            # the record so re-running `--snapshot-update` doesn't report
            # untouched baselines as "created". A changed figure keeps the
            # GENERATED record, since its baseline is genuinely being rewritten.
            if unchanged:
                self._record(
                    stem,
                    ImageResult(
                        status=ImageMatchStatus.MATCH, tolerance=params.tolerance
                    ),
                )
            elif self._mpl_snapshot_dir is not None:  # pragma: no branch
                # This baseline is about to be overwritten with something
                # else, which is the only thing that can outdate a variant.
                # Scanning here rather than in `get_location` keeps the
                # warning to the directories a rewrite really touched: an
                # unchanged snapshot, or a brand-new one in an unrelated
                # module, must not drag another module's tags into it.
                self._note_variant_dirs(Path(self._mpl_snapshot_dir))
            return unchanged

        # Bytes-equality fast path: deterministic rendering means identical
        # figures produce identical PNG bytes, so we can short-circuit the
        # disk I/O + compare_images() for the common green-path case.
        if (
            baseline_bytes is not None
            and test_bytes == baseline_bytes
            and not self._mpl_keep_match_artifacts
        ):
            self._mpl_last_failure_message = None
            self._record(
                stem,
                ImageResult(status=ImageMatchStatus.MATCH, tolerance=params.tolerance),
            )
            return True

        artifact_dir = self._require_artifact_dir()
        result = run_comparison(
            test_bytes=test_bytes,
            baseline_bytes=baseline_bytes,
            tolerance=params.tolerance,
            diff_dir=artifact_dir,
            stem=stem,
            ext=self.file_extension,
            keep_on_match=self._mpl_keep_match_artifacts,
        )
        self._mpl_last_failure_message = result.error_message
        self._record(stem, result)
        return is_passing(result.status)

    def _decide_variant_write(
        self, params: SnapshotParams, stem: str, test_bytes: bytes
    ) -> bool:
        """Decide what a variant-writing run does with one snapshot.

        The comparison is against the **canonical** baseline at the effective
        tolerance, not against the variant and not by byte equality: a
        sub-tolerance difference is not worth a variant file, and a variant
        that is byte-equal to what was just rendered is not worth rewriting.

        The variant file is written here rather than by syrupy, and the return
        value is always `True`. Syrupy writes the location `get_location`
        reports, which is the canonical baseline this run must not touch, and
        it can only be told to write by failing the assertion — which would
        also report the pin run's every write as a test failure.

        Comparison artifacts survive only on the record that references
        them: the report-mode ``GENERATED`` record carries the canonical
        comparison, everything else is unlinked so a pin run without a
        report leaves `figure-report/` empty.

        Args:
            params: Effective per-assertion parameters.
            stem: Filename stem of the current snapshot.
            test_bytes: Freshly rendered PNG bytes.

        Returns:
            `True`, always: the assertion passes and syrupy queues no write.

        Raises:
            RuntimeError: If the canonical baseline vanished after it (or the
                variant) was read — the snapshot must not live on as a
                variant only.
        """
        self._mpl_last_failure_message = None
        # Every record below describes a comparison against the canonical
        # baseline; the variant read at baseline-read time only feeds the
        # byte-equality shortcut.
        self._mpl_baseline_variant = None
        variant_path = self._current_variant_path()
        if variant_path is None:  # pragma: no cover
            # No tag to pin to, which `resolve_config` refuses up front.
            msg = "variant-writing mode reached without a variant tag."
            raise RuntimeError(msg)
        canonical_bytes = self._read_canonical_bytes()
        # The practical case — variant read fine, canonical deleted — is
        # caught at read time and refused by `serialize()`; this only fires
        # when the canonical disappears between that check and this one.
        if canonical_bytes is None:  # pragma: no cover
            raise RuntimeError(_build_variant_only_message(stem, variant_path))
        canonical_result = run_comparison(
            test_bytes=test_bytes,
            baseline_bytes=canonical_bytes,
            tolerance=params.tolerance,
            diff_dir=self._require_artifact_dir(),
            stem=stem,
            ext=self.file_extension,
            keep_on_match=self._mpl_keep_match_artifacts,
        )

        if is_passing(canonical_result.status):
            # This environment renders what the canonical baseline already
            # holds, so any variant it used to need is now noise.
            if variant_path.exists():
                variant_path.unlink()
                # An emptied tag directory is not "an environment with
                # variants": left behind it would keep feeding the
                # stale-variant warning after the last variant is gone, and
                # a pin run that writes nothing never creates one at all.
                # `<tag>/<module>/` goes first, then the tag directory, then
                # the variant root — each only when the one below it was the
                # last thing it held, since the suppressed `OSError` from a
                # non-empty directory skips the rest.
                with contextlib.suppress(OSError):
                    variant_path.parent.rmdir()
                    variant_path.parent.parent.rmdir()
                    variant_path.parent.parent.parent.rmdir()
                if (
                    self._mpl_collector is not None and self._mpl_nodeid is not None
                ):  # pragma: no branch
                    self._mpl_collector.record_deletion(self._record_key(stem))
            self._record(stem, canonical_result)
            return True

        if variant_path.exists() and variant_path.read_bytes() == test_bytes:
            # The mismatch artifacts describe a difference the existing
            # variant already answers; no record references them.
            self._discard_artifacts(canonical_result)
            self._record(
                stem,
                ImageResult(status=ImageMatchStatus.MATCH, tolerance=params.tolerance),
            )
            return True

        # This environment needs a variant, and it is this plugin that writes
        # it: `serialize()` already recorded the write as GENERATED.
        variant_path.parent.mkdir(parents=True, exist_ok=True)
        variant_path.write_bytes(test_bytes)

        if self._mpl_keep_match_artifacts:
            # A report is coming: keep the canonical comparison on the
            # GENERATED record so the report can show what the variant
            # answers. The mismatch message would misread as a failure.
            self._record(
                stem,
                replace(
                    canonical_result,
                    status=ImageMatchStatus.GENERATED,
                    error_message=None,
                ),
            )
        else:
            self._discard_artifacts(canonical_result)
            self._record(stem, _GENERATED_RESULT)
        return True

    @staticmethod
    def _discard_artifacts(result: ImageResult) -> None:
        """Unlink the comparison artifacts of *result*.

        Args:
            result: The comparison whose on-disk artifacts are dropped.
        """
        for path in (result.actual_path, result.baseline_path, result.diff_path):
            if path is not None:
                path.unlink(missing_ok=True)

    def _current_variant_path(self) -> Path | None:
        """Return the variant path for the snapshot being asserted.

        Returns:
            The path, or `None` when no canonical location was resolved (no
            active tag).
        """
        if self._mpl_canonical_location is None:
            return None
        return self._build_variant_location(self._mpl_canonical_location)

    def _read_canonical_bytes(self) -> bytes | None:
        """Return the canonical baseline bytes for the current snapshot.

        Returns:
            The bytes, or `None` when there is no canonical baseline on disk.
        """
        if self._mpl_canonical_location is None:  # pragma: no cover
            return None
        path = Path(self._mpl_canonical_location)
        return path.read_bytes() if path.exists() else None

    def _require_artifact_dir(self) -> Path:
        """Return the `figure-report/` subdirectory for the current test.

        Returns:
            The directory comparison artifacts are written to.

        Raises:
            RuntimeError: If the assertion did not stamp a collector with
                `results_root` before this method ran.
        """
        if (
            self._mpl_collector is None or self._mpl_collector.results_root is None
        ):  # pragma: no cover
            msg = "MplSnapshotAssertion did not stamp collector with results_root"
            raise RuntimeError(msg)
        return self._mpl_collector.results_root / self._artifact_subdir()

    def diff_lines(  # ty: ignore[invalid-method-override]
        self,
        serialized_data: Any,
        snapshot_data: Any,
    ) -> list[str]:
        """Return the failure message for pytest's terminal output.

        Binary pixel diffs are meaningless as text, so we surface the
        message produced by `run_comparison()` instead.

        Args:
            serialized_data: Ignored.
            snapshot_data: Ignored.

        Returns:
            The failure message split into lines.
        """
        msg = self._mpl_last_failure_message or "Figure comparison failed."
        return msg.splitlines()

    def _artifact_subdir(self) -> Path:
        """Return a per-test subdirectory for `figure-report/` artifacts.

        Different test modules may declare tests with the same name (e.g.
        ``test_plot[True-kwargs9-properties9]``). Without disambiguation,
        their actual/baseline/diff PNGs would share the same path, and
        xdist workers running them concurrently would race on those files —
        producing spurious failures with all-black diff images.

        Mirrors the test file's location relative to the pytest rootpath.
        Falls back to ``<basename>-<sha1>`` when the test file lives outside
        the rootpath.

        Returns:
            A relative path suitable for joining under `results_root`.
        """
        if self._mpl_test_filepath is None:
            return Path()
        file = Path(self._mpl_test_filepath)
        if self._mpl_rootpath is not None:
            try:
                return file.relative_to(self._mpl_rootpath).with_suffix("")
            except ValueError:
                pass
        digest = hashlib.sha1(str(file).encode(), usedforsecurity=False).hexdigest()[:8]
        return Path(f"{file.stem}-{digest}")

    def _stamped_state(self) -> tuple[SnapshotParams, str]:
        """Return the stamped (params, snapshot stem) pair.

        Returns:
            The `SnapshotParams` and snapshot stem stamped by
            `MplSnapshotAssertion._assert` before this method runs.

        Raises:
            RuntimeError: If `MplSnapshotAssertion` did not stamp the
                per-call state before this method ran.
        """
        if self._mpl_params is None or self._mpl_last_stem is None:  # pragma: no cover
            msg = "MplSnapshotAssertion did not stamp per-call state"
            raise RuntimeError(msg)
        return self._mpl_params, self._mpl_last_stem

    def _record_key(self, stem: str) -> str:
        """Return the collector key identifying the current snapshot.

        Every bucket the terminal summary prints is keyed this way, so a
        stem alone would be ambiguous the moment two modules declare a test
        of the same name — the case `_artifact_subdir` already guards.

        Args:
            stem: Filename stem of the current snapshot.

        Returns:
            The pytest node id plus `::<stem>`.
        """
        return f"{self._mpl_nodeid}::{stem}"

    def _record(self, stem: str, result: ImageResult) -> None:
        """Push a `ResultRecord` into the shared collector.

        Args:
            stem: Filename stem of the current snapshot.
            result: Image result to record.
        """
        collector = self._mpl_collector
        # `_mpl_collector` is bound at `pytest_configure` and `_mpl_nodeid`
        # is stamped per assertion; both are populated under normal pytest
        # flow. The guard catches direct extension instantiation in unit tests.
        if collector is None or self._mpl_nodeid is None:
            return
        collector.record(
            ResultRecord.from_image_result(
                test_name=self._record_key(stem),
                result=result,
                results_root=collector.results_root,
                baseline_variant=self._mpl_baseline_variant,
            )
        )


_GENERATED_RESULT = ImageResult(status=ImageMatchStatus.GENERATED)
"""Synthetic `ImageResult` recorded for update-mode writes; immutable, shared."""


def _build_variant_only_message(stem: str, variant_location: Path | None) -> str:
    """Build the message refusing a snapshot with no canonical baseline.

    Args:
        stem: Filename stem of the current snapshot.
        variant_location: Path of the variant baseline shadowing the missing
            canonical one, or `None` when no variant exists either.

    Returns:
        The `RuntimeError` message; raising at the call site is what aborts
        the assertion, and with it any queued snapshot write, when the
        canonical baseline is missing.
    """
    shadowed = ""
    if variant_location is not None and variant_location.exists():
        shadowed = f" A variant baseline shadows it at {variant_location}."
    return (
        f"canonical baseline missing for {stem!r}.{shadowed} A snapshot cannot "
        "exist as a variant only: nothing regenerates a variant except a pin "
        "run comparing it against a canonical baseline. Create the canonical "
        "baseline with --snapshot-update alone, without "
        "--snapshot-matplotlib-pin-variant, or delete the variant."
    )


def _coerce_bytes(data: Any) -> bytes:
    """Coerce *data* to `bytes` for comparison.

    Args:
        data: Either `bytes` or an object supporting the buffer protocol.

    Returns:
        Plain `bytes`.
    """
    if isinstance(data, bytes):
        return data
    return bytes(memoryview(data))
