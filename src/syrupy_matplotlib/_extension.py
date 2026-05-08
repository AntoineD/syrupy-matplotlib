"""Syrupy extension that serializes and compares matplotlib figures.

`MplFigureExtension` subclasses syrupy's `SingleFileSnapshotExtension` so
each snapshot is a standalone `.png` under `__snapshots__/<module_stem>/`.

Per-assertion state (`SnapshotParams`, node id, snapshot stem) is stamped
onto the extension instance by `MplSnapshotAssertion._assert` before
`matches()` runs — syrupy's `matches(*, serialized_data, snapshot_data)`
signature does not thread that context through otherwise. Session-wide
state (`_mpl_collector`, `_mpl_update_snapshots`) is bound once at
`pytest_configure` time on the class. The diagnostic-artifact directory
rides on `collector.results_root`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from matplotlib.figure import Figure
from matplotlib.testing.decorators import remove_ticks_and_titles
from syrupy.extensions.single_file import SingleFileSnapshotExtension
from syrupy.extensions.single_file import WriteMode

from ._comparison import run_comparison
from ._figures import save_figure_to_bytes
from ._reporting import ResultRecord
from ._types import ImageMatchStatus
from ._types import ImageResult
from ._types import is_passing

if TYPE_CHECKING:
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
    """Shared report collector; bound once at `pytest_configure` time."""

    _mpl_rootpath: Path | None = None
    """Pytest rootpath; bound once at `pytest_configure` time. Used to namespace
    artifact paths under `figure-report/` so xdist workers running tests in
    different modules with overlapping test names don't clobber each other."""

    _mpl_update_snapshots: bool = False
    """`True` when `--snapshot-update` is active; bound at `pytest_configure` time."""

    _mpl_keep_match_artifacts: bool = False
    """`True` when a report format is requested; bound once at `pytest_configure` time.
    When `False`, MATCH comparisons leave no files in `figure-report/`."""

    _mpl_nodeid: str | None = None
    """Full pytest node id, used as the `ResultRecord` key."""

    _mpl_test_filepath: str | None = None
    """Absolute path of the current test's source file; stamped by the assertion."""

    _mpl_last_stem: str | None = None
    """Filename stem of the current snapshot; stamped by the assertion."""

    _mpl_last_failure_message: str | None = None
    """Failure message for the most recent `matches()` call, or `None`."""

    def serialize(
        self,
        data: Any,
        *,
        exclude: Any = None,
        include: Any = None,
        matcher: Any = None,
    ) -> bytes:
        """Render a `Figure` to deterministic PNG bytes.

        Args:
            data: The operand passed to `==`. Must be a `matplotlib.figure.Figure`.
            exclude: Unused (syrupy signature).
            include: Unused (syrupy signature).
            matcher: Unused (syrupy signature).

        Returns:
            Raw PNG bytes ready for on-disk comparison.

        Raises:
            TypeError: If *data* is not a `matplotlib.figure.Figure`.
        """
        if not isinstance(data, Figure):
            msg = f"snapshot comparison expected a Figure, got {type(data).__name__}."
            raise TypeError(msg)
        params, stem = self._stamped_state()
        fig: Figure = data
        if params.remove_text:
            remove_ticks_and_titles(fig)

        # Update mode: ``matches()`` is not called for brand-new baselines
        # (syrupy writes the snapshot directly). Emit a "created" record
        # here so the terminal summary can count it.
        if self._mpl_update_snapshots:
            self._record(stem, _GENERATED_RESULT)

        return save_figure_to_bytes(fig, self.file_extension, params.savefig_kwargs)

    def matches(self, *, serialized_data: Any, snapshot_data: Any) -> bool:
        """Run pixel comparison against the stored baseline.

        Args:
            serialized_data: Bytes produced by `serialize()`.
            snapshot_data: Bytes read from the on-disk baseline, or `None`.

        Returns:
            `True` when the comparison passes.

        Raises:
            RuntimeError: If the assertion did not stamp a collector with
                `results_root` before this method ran.
        """
        params, stem = self._stamped_state()
        test_bytes = _coerce_bytes(serialized_data)
        baseline_bytes = (
            _coerce_bytes(snapshot_data) if snapshot_data is not None else None
        )

        if self._mpl_update_snapshots:
            # `serialize()` already recorded the GENERATED result; don't double-count.
            self._mpl_last_failure_message = None
            return test_bytes == baseline_bytes

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

        if (
            self._mpl_collector is None or self._mpl_collector.results_root is None
        ):  # pragma: no cover
            msg = "MplSnapshotAssertion did not stamp collector with results_root"
            raise RuntimeError(msg)

        artifact_dir = self._mpl_collector.results_root / self._artifact_subdir()
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
