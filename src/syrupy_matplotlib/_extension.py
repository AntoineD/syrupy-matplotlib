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

import hashlib
import warnings
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from matplotlib.figure import Figure
from matplotlib.testing.decorators import remove_ticks_and_titles
from syrupy.data import SnapshotCollections
from syrupy.extensions.single_file import SingleFileSnapshotExtension
from syrupy.extensions.single_file import WriteMode

from ._comparison import run_comparison
from ._figures import save_figure_to_bytes
from ._reporting import ResultRecord
from ._types import ImageMatchStatus
from ._types import ImageResult
from ._types import is_passing

if TYPE_CHECKING:
    from syrupy.location import PyTestLocation
    from syrupy.types import SnapshotIndex

    from ._params import SnapshotParams
    from ._reporting import ResultCollector


class MplFigureExtension(SingleFileSnapshotExtension):
    """One `.png` per snapshot under `__snapshots__/<module_stem>/`.

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

    _mpl_baseline_variant: str | None = None
    """Tag of the variant actually served to `matches()`, or `None` when the
    canonical baseline was used."""

    _mpl_canonical_missing: bool = False
    """`True` when variant-writing mode found no canonical baseline to
    compare against; makes `serialize()` refuse the snapshot."""

    _mpl_scanned_dirs: set[str] = set()  # ruff: ignore[mutable-class-default]
    """Snapshot directories already scanned for variant subdirectories.
    Class-level so the scan happens once per directory, not once per
    snapshot; cleared by `pytest_unconfigure`."""

    # ── Baseline location: variant first, canonical as fallback ─────────────

    @classmethod
    def get_location(
        cls, *, test_location: PyTestLocation, index: SnapshotIndex
    ) -> str:
        """Return the path of the baseline this assertion reads or writes.

        Four cases, in order:

        - no tag (matplotlib metadata unreadable): the canonical path;
        - variant-writing mode: the variant path, always — this is what makes
          `--snapshot-update` write there and leave canonical alone, with no
          special-casing in the write path itself;
        - plain `--snapshot-update`: the canonical path, even when a variant
          exists, so a re-baseline never lands in a variant directory;
        - comparison: the variant path when that file exists, else canonical.

        Args:
            test_location: Syrupy's wrapper around the current pytest node.
            index: Snapshot index within the test.

        Returns:
            Absolute path to the baseline file, as a string.
        """
        canonical = super().get_location(test_location=test_location, index=index)
        variant = cls._build_variant_location(canonical)
        if variant is None:
            return canonical
        if cls._mpl_write_variants:
            return str(variant)
        if cls._mpl_update_snapshots:
            cls._note_variant_dirs(Path(canonical).parent)
            return canonical
        return str(variant) if variant.exists() else canonical

    def read_snapshot_data_from_location(
        self, *, snapshot_location: str, snapshot_name: str, session_id: str
    ) -> Any:
        """Read the baseline, falling back from the variant to the canonical.

        The fallback applies in update mode too, and has to: syrupy skips
        `matches()` entirely when the read comes back `None` and writes the
        snapshot straight to disk, which would make every variant-writing run
        create a variant unconditionally instead of only where the canonical
        baseline really differs.

        Args:
            snapshot_location: Path chosen by `get_location`.
            snapshot_name: Snapshot stem (unused by the single-file base).
            session_id: Syrupy session id.

        Returns:
            The baseline bytes, or `None` when neither baseline exists.
        """
        self._mpl_canonical_location = None
        self._mpl_baseline_variant = None
        self._mpl_canonical_missing = False

        data = super().read_snapshot_data_from_location(
            snapshot_location=snapshot_location,
            snapshot_name=snapshot_name,
            session_id=session_id,
        )
        canonical = self._resolve_canonical_location(snapshot_location)
        if canonical is None:
            # Already the canonical location; nothing to fall back to.
            return data

        self._mpl_canonical_location = canonical
        if data is not None:
            self._mpl_baseline_variant = self._mpl_variant
            return data

        fallback = super().read_snapshot_data_from_location(
            snapshot_location=canonical,
            snapshot_name=snapshot_name,
            session_id=session_id,
        )
        if fallback is None and self._mpl_write_variants:
            self._mpl_canonical_missing = True
        return fallback

    def discover_snapshots(
        self,
        *,
        test_location: PyTestLocation,
        ignore_extensions: list[str] | None = None,
    ) -> SnapshotCollections:
        """Return the snapshots syrupy may report as unused, and only those.

        `syrupy.utils.walk_snapshot_dir` recurses (`rglob`), so the base
        implementation returns variant files alongside canonical ones. Left
        alone, a plain `--snapshot-update` deletes every variant as "unused",
        and a variant-writing run does the same to the canonical baselines.
        Restricting discovery to the directory this run actually maintains
        closes both.

        Comparison runs additionally drop canonical baselines that a variant
        shadows: the run reads the variant, so the canonical never enters
        syrupy's `used` set and would be reported unused — which fails the
        session, since unused snapshots set a non-zero exit status.

        Args:
            test_location: Syrupy's wrapper around the current pytest node.
            ignore_extensions: Extensions syrupy was told to skip.

        Returns:
            The filtered snapshot collections.
        """
        discovered = super().discover_snapshots(
            test_location=test_location, ignore_extensions=ignore_extensions
        )
        canonical_dir = Path(self.dirname(test_location=test_location))
        active_dir = canonical_dir
        if self._mpl_write_variants:
            active_dir = canonical_dir / self._mpl_variant

        filtered = SnapshotCollections()
        for collection in discovered:
            location = Path(collection.location)
            if location.parent != active_dir:
                continue
            if not self._mpl_update_snapshots and self._is_shadowed(location):
                continue
            filtered.add(collection)
        return filtered

    @classmethod
    def write_snapshot(cls, *, snapshot_location: str, snapshots: list[Any]) -> None:
        """Write baselines, muting syrupy's layout warning for variant paths.

        `AbstractSyrupyExtension.write_snapshot` warns when it cannot relate
        the snapshot location to the test location, and
        `PyTestLocation._matches_snapshot_basename` only accepts a file
        sitting directly in `__snapshots__/<module_stem>/`. Every variant is
        one directory deeper by design, so the warning would fire once per
        written file on the very command the docs tell users to run.

        Overriding a method syrupy documents as final, and matching on its
        warning text, are both covered by the `syrupy>=5.1,<6` pin.

        Args:
            snapshot_location: Path the snapshots are written to.
            snapshots: Syrupy's `(data, test_location, index)` tuples.
        """
        if not cls._mpl_write_variants:
            super().write_snapshot(
                snapshot_location=snapshot_location, snapshots=snapshots
            )
            return
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"\nCan not relate snapshot location",
                category=UserWarning,
            )
            super().write_snapshot(
                snapshot_location=snapshot_location, snapshots=snapshots
            )

    @classmethod
    def _build_variant_location(cls, canonical: str) -> Path | None:
        """Return the variant path matching *canonical*.

        Args:
            canonical: Canonical baseline path.

        Returns:
            The path under the tag subdirectory, or `None` when no variant
            tag is active.
        """
        if not cls._mpl_variant:
            return None
        path = Path(canonical)
        return path.parent / cls._mpl_variant / path.name

    @classmethod
    def _resolve_canonical_location(cls, snapshot_location: str) -> str | None:
        """Return the canonical path for a variant location.

        Args:
            snapshot_location: Path `get_location` produced.

        Returns:
            The canonical path when *snapshot_location* is inside the active
            variant directory, otherwise `None`.
        """
        if not cls._mpl_variant:
            return None
        path = Path(snapshot_location)
        if path.parent.name != cls._mpl_variant:
            return None
        return str(path.parent.parent / path.name)

    @classmethod
    def _is_shadowed(cls, canonical: Path) -> bool:
        """Return whether a variant baseline overrides *canonical*.

        Args:
            canonical: Canonical baseline path.

        Returns:
            `True` when the matching variant file exists on disk.
        """
        variant = cls._build_variant_location(str(canonical))
        return variant is not None and variant.exists()

    @classmethod
    def _note_variant_dirs(cls, snapshot_dir: Path) -> None:
        """Record the variant directories sitting next to canonical baselines.

        Feeds the warning a canonical re-baseline emits: the plugin cannot
        tell whether those variants still describe their environments, having
        never rendered under them.

        Args:
            snapshot_dir: The `__snapshots__/<module_stem>` directory.
        """
        collector = cls._mpl_collector
        if collector is None:  # pragma: no cover
            return
        key = str(snapshot_dir)
        if key in cls._mpl_scanned_dirs:
            return
        cls._mpl_scanned_dirs.add(key)
        try:
            entries = list(snapshot_dir.iterdir())
        except OSError:  # pragma: no cover
            return
        for entry in entries:
            if entry.is_dir():
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
            RuntimeError: If variant-writing mode found no canonical baseline
                to compare against.
        """
        if not isinstance(data, Figure):
            msg = f"snapshot comparison expected a Figure, got {type(data).__name__}."
            raise TypeError(msg)
        params, stem = self._stamped_state()
        # Raising is what stops the write: syrupy queues a snapshot write for
        # any failed assertion in update mode, and only an exception escaping
        # `_assert`'s try block skips it. Refusing here also keeps the variant
        # subdirectory from being created at all.
        if self._mpl_canonical_missing:
            msg = (
                f"canonical baseline missing for {stem!r}; create it first "
                "with --snapshot-update alone, without "
                "--snapshot-matplotlib-pin-variant. A snapshot cannot exist "
                "as a variant only."
            )
            raise RuntimeError(msg)
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

        Returning `False` is how the variant gets written — syrupy queues the
        write for any non-matching assertion in update mode, at the path
        `get_location` returned, which is the variant path in this mode.

        Args:
            params: Effective per-assertion parameters.
            stem: Filename stem of the current snapshot.
            test_bytes: Freshly rendered PNG bytes.

        Returns:
            `True` when nothing needs to be written, `False` to have syrupy
            write the variant.
        """
        self._mpl_last_failure_message = None
        matched = ImageResult(status=ImageMatchStatus.MATCH, tolerance=params.tolerance)
        variant_path = self._current_variant_path()
        canonical_result = run_comparison(
            test_bytes=test_bytes,
            baseline_bytes=self._read_canonical_bytes(),
            tolerance=params.tolerance,
            diff_dir=self._require_artifact_dir(),
            stem=stem,
            ext=self.file_extension,
            keep_on_match=self._mpl_keep_match_artifacts,
        )

        if is_passing(canonical_result.status):
            # This environment renders what the canonical baseline already
            # holds, so any variant it used to need is now noise.
            if variant_path is not None and variant_path.exists():
                variant_path.unlink()
                if self._mpl_collector is not None:  # pragma: no branch
                    self._mpl_collector.record_deletion(stem)
            self._record(stem, matched)
            return True

        if (
            variant_path is not None
            and variant_path.exists()
            and variant_path.read_bytes() == test_bytes
        ):
            self._record(stem, matched)
            return True

        self._record(stem, _GENERATED_RESULT)
        return False

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
                test_name=f"{self._mpl_nodeid}::{stem}",
                result=result,
                results_root=collector.results_root,
                baseline_variant=self._mpl_baseline_variant,
            )
        )


_GENERATED_RESULT = ImageResult(status=ImageMatchStatus.GENERATED)
"""Synthetic `ImageResult` recorded for update-mode writes; immutable, shared."""


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
