"""`SnapshotAssertion` subclass that threads per-call matplotlib kwargs.

Syrupy's `SnapshotAssertion.__call__` accepts a closed set of kwargs
(`name`, `matcher`, `diff`, `exclude`, `include`, `extension_class`) with
no generic passthrough. We subclass to:

1. Accept matplotlib-specific overrides (`tolerance`, `savefig_kwargs`,
   `remove_text`) on `snapshot_matplotlib(...)`.
2. Stamp per-assertion state onto the extension instance just before
   `matches()` runs — `matches()` receives only serialized and snapshot
   data.
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING
from typing import Any

from matplotlib.figure import Figure
from syrupy.assertion import SnapshotAssertion

from ._comparison import run_comparison
from ._extension import MplFigureExtension
from ._extension import _coerce_bytes
from ._reporting import ResultRecord
from ._types import ImageMatchStatus
from ._types import ImageResult

if TYPE_CHECKING:
    from syrupy.extensions.base import AbstractSyrupyExtension
    from syrupy.location import PyTestLocation
    from syrupy.session import SnapshotSession

    from ._params import SnapshotParams
    from ._reporting import ResultCollector


class MplSnapshotAssertion(SnapshotAssertion):
    """Matplotlib-aware `SnapshotAssertion`.

    Not a dataclass: syrupy's base is, but we define an explicit `__init__`
    so our extra fields don't have to satisfy dataclass ordering rules.
    """

    def __init__(
        self,
        *,
        session: SnapshotSession,
        extension_class: type[AbstractSyrupyExtension],
        test_location: PyTestLocation,
        update_snapshots: bool,
        mpl_params: SnapshotParams,
        auto: bool = True,
    ) -> None:
        """Args:
        session: Active syrupy `SnapshotSession` (from `config._syrupy`).
        extension_class: Extension class used to serialize and compare.
        test_location: Syrupy's wrapper around the current pytest node.
        update_snapshots: Value of `--snapshot-update`.
        mpl_params: Default per-assertion parameters for this fixture.
        auto: Initial value for the auto-discover / auto-assert /
            auto-close behavior. May be flipped per-test via
            ``snapshot_matplotlib(auto=...)``.
        """  # ruff: ignore[missing-blank-line-after-summary]
        super().__init__(
            session=session,
            extension_class=extension_class,
            test_location=test_location,
            update_snapshots=update_snapshots,
        )
        self._mpl_params: SnapshotParams = mpl_params
        self._mpl_auto: bool = auto
        # Weak, so a closed figure's entry dies with it — a plain id() set
        # would let a new figure reusing the address masquerade as asserted.
        self._mpl_asserted_figs: weakref.WeakSet[Figure] = weakref.WeakSet()

    def __call__(  # ty: ignore[invalid-method-override]
        self,
        *,
        tolerance: float | None = None,
        savefig_kwargs: dict[str, Any] | None = None,
        remove_text: bool | None = None,
        auto: bool | None = None,
        name: str | None = None,
        matcher: Any = None,
        diff: Any = None,
        exclude: Any = None,
        include: Any = None,
        extension_class: Any = None,
    ) -> MplSnapshotAssertion:
        """Configure the next `== snapshot_matplotlib` assertion.

        Matplotlib-specific kwargs are stashed temporarily on `self`;
        syrupy-native kwargs forward to the parent's `__call__`. All
        overrides are reverted by `_post_assert` after the assertion runs —
        use `set_defaults()` for values that must hold for the whole test.

        Args:
            tolerance: RMS threshold override.
            savefig_kwargs: Override for extra `Figure.savefig()` kwargs.
            remove_text: Whether to strip tick labels and titles before
                serializing.
            auto: Enable/disable the fixture's auto-discover / auto-assert /
                auto-close behavior for the rest of the test. Unlike the other
                overrides, this value persists (not reverted after one
                assertion) since auto teardown runs once. This is the only
                supported way to toggle the behavior per test.
            name: Explicit snapshot name (disables auto-indexing).
            matcher: Syrupy property matcher.
            diff: Syrupy diff-index argument.
            exclude: Syrupy property filter.
            include: Syrupy property filter.
            extension_class: Alternative extension class for this assertion.

        Returns:
            `self` (same instance, with temporary overrides applied).
        """
        if any(v is not None for v in (tolerance, savefig_kwargs, remove_text)):
            old_cfg = self._mpl_params
            self._mpl_params = old_cfg.merge(
                tolerance=tolerance,
                savefig_kwargs=savefig_kwargs,
                remove_text=remove_text,
            )
            self._post_assert_actions.append(
                lambda: setattr(self, "_mpl_params", old_cfg)
            )
        if auto is not None:
            self._mpl_auto = bool(auto)
        return super().__call__(  # ty: ignore[invalid-return-type]
            name=name,
            matcher=matcher,
            diff=diff,
            exclude=exclude,
            include=include,
            extension_class=extension_class,
        )

    def set_defaults(
        self,
        *,
        tolerance: float | None = None,
        savefig_kwargs: dict[str, Any] | None = None,
        remove_text: bool | None = None,
        auto: bool | None = None,
    ) -> MplSnapshotAssertion:
        """Set defaults for every later assertion made through this fixture.

        `snapshot_matplotlib(...)` applies its overrides to the next
        assertion only — they are reverted by `_post_assert`. This method
        rebinds the fixture's own params instead, so the values hold for
        every assertion in the test, including the ones the auto path makes
        at the end of the call phase.

        Intended for wrapper fixtures that raise the bar for a whole
        package::

            @pytest.fixture
            def snapshot_matplotlib(snapshot_matplotlib):
                return snapshot_matplotlib.set_defaults(tolerance=5.0)

        `style` and `backend` are absent for the same reason `merge()`
        omits them: they must be active before the figure is drawn.

        Args:
            tolerance: RMS threshold for every later assertion.
            savefig_kwargs: Extra `Figure.savefig()` kwargs (replaces, does
                not merge).
            remove_text: Whether to strip tick labels and titles.
            auto: Enable/disable auto-discover / auto-assert / auto-close.

        Returns:
            `self`, so the call can be returned straight from a fixture.
        """
        self._mpl_params = self._mpl_params.merge(
            tolerance=tolerance,
            savefig_kwargs=savefig_kwargs,
            remove_text=remove_text,
        )
        if auto is not None:
            self._mpl_auto = bool(auto)
        return self

    def _assert(self, data: Any) -> bool:
        """Stamp per-call state onto the extension, then delegate to syrupy.

        When the on-disk baseline is missing, syrupy's `_assert` returns
        `False` without calling `extension.matches()`, so no comparison
        record is written and the session summary undercounts the failure.
        We build the `MISSING` record afterwards to keep the summary
        consistent, writing the rendered figure to `figure-report/` so the
        report has something to show.

        Args:
            data: The left-hand operand of `==` (a `Figure` for the default
                extension).

        Returns:
            `True` on PASS (or update-mode write), `False` otherwise.
        """
        ext = self.extension
        stem = ext.get_snapshot_name(test_location=self.test_location, index=self.index)
        if isinstance(ext, MplFigureExtension):  # pragma: no branch
            ext._mpl_params = self._mpl_params
            ext._mpl_nodeid = self.test_location.nodeid
            ext._mpl_test_filepath = self.test_location.filepath
            ext._mpl_last_stem = stem
            ext._mpl_last_failure_message = None
        if isinstance(data, Figure):
            self._mpl_asserted_figs.add(data)

        success = super()._assert(data)

        if success or self.update_snapshots or not isinstance(ext, MplFigureExtension):
            return success
        # `_execution_results`, `_executions` and `recalled_data` are syrupy
        # private API. The `syrupy>=5.1,<6` pin in pyproject.toml is therefore
        # load-bearing for this missing-baseline detection; a major syrupy bump
        # must re-validate it. `test_missing_baseline_fails` guards the path.
        latest = self._execution_results.get(self._executions - 1)
        if latest is None or latest.recalled_data is not None:
            return success
        # Syrupy bypassed `matches()` due to missing baseline. Record it.
        collector = ext._mpl_collector
        if collector is None:  # pragma: no cover
            return success
        missing = self._build_missing_result(ext, collector, latest.asserted_data, stem)
        ext._mpl_last_failure_message = missing.error_message
        collector.record(
            ResultRecord.from_image_result(
                test_name=f"{self.test_location.nodeid}::{stem}",
                result=missing,
                results_root=collector.results_root,
            )
        )
        return success

    def _build_missing_result(
        self,
        ext: MplFigureExtension,
        collector: ResultCollector,
        serialized: Any,
        stem: str,
    ) -> ImageResult:
        """Build the `MISSING` result, saving the rendered figure when possible.

        A missing baseline is the one failure mode where the user has nothing
        to compare against, which makes seeing what was actually drawn more
        useful than usual — so the serialized PNG is written under
        `figure-report/` and linked from the result, exactly as a `DIFF`
        would be.

        Args:
            ext: The stamped extension instance.
            collector: Collector holding the artifact root.
            serialized: Bytes syrupy serialized for this assertion, or `None`
                when serialization raised.
            stem: Filename stem of the current snapshot.

        Returns:
            A `MISSING` `ImageResult`, carrying `actual_path` when the
            rendered figure could be written.
        """
        if serialized is None or collector.results_root is None:
            return ImageResult(
                status=ImageMatchStatus.MISSING,
                tolerance=self._mpl_params.tolerance,
                error_message="Baseline image not found on disk.",
            )
        return run_comparison(
            test_bytes=_coerce_bytes(serialized),
            baseline_bytes=None,
            tolerance=self._mpl_params.tolerance,
            diff_dir=collector.results_root / ext._artifact_subdir(),
            stem=stem,
            ext=ext.file_extension,
        )
