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

from typing import TYPE_CHECKING
from typing import Any

from syrupy.assertion import SnapshotAssertion

if TYPE_CHECKING:
    from syrupy.extensions.base import AbstractSyrupyExtension
    from syrupy.location import PyTestLocation
    from syrupy.session import SnapshotSession

    from ._params import SnapshotParams


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
        """  # noqa: D205
        super().__init__(
            session=session,
            extension_class=extension_class,
            test_location=test_location,
            update_snapshots=update_snapshots,
        )
        self._mpl_params: SnapshotParams = mpl_params
        self._mpl_auto: bool = auto
        self._mpl_asserted_fig_ids: set[int] = set()

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
        overrides are reverted by `_post_assert` after the assertion runs.

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

    def _assert(self, data: Any) -> bool:
        """Stamp per-call state onto the extension, then delegate to syrupy.

        When the on-disk baseline is missing, syrupy's `_assert` returns
        `False` without calling `extension.matches()`, so no comparison
        record is written and the session summary undercounts the failure.
        We synthesize a `MISSING` record afterwards to keep the summary
        consistent.

        Args:
            data: The left-hand operand of `==` (a `Figure` for the default
                extension).

        Returns:
            `True` on PASS (or update-mode write), `False` otherwise.
        """
        from ._extension import MplFigureExtension
        from ._reporting import ResultRecord
        from ._types import ImageMatchStatus
        from ._types import ImageResult

        ext = self.extension
        stem = ext.get_snapshot_name(test_location=self.test_location, index=self.index)
        if isinstance(ext, MplFigureExtension):  # pragma: no branch
            ext._mpl_params = self._mpl_params
            ext._mpl_nodeid = self.test_location.nodeid
            ext._mpl_test_filepath = self.test_location.filepath
            ext._mpl_last_stem = stem
            ext._mpl_last_failure_message = None
        self._mpl_asserted_fig_ids.add(id(data))

        success = super()._assert(data)

        if success or self.update_snapshots or not isinstance(ext, MplFigureExtension):
            return success
        latest = self._execution_results.get(self._executions - 1)
        if latest is None or latest.recalled_data is not None:
            return success
        # Syrupy bypassed `matches()` due to missing baseline. Record it.
        missing = ImageResult(
            status=ImageMatchStatus.MISSING,
            tolerance=self._mpl_params.tolerance,
            error_message="Baseline image not found on disk.",
        )
        ext._mpl_last_failure_message = missing.error_message
        collector = ext._mpl_collector
        if collector is None:  # pragma: no cover
            return success
        collector.record(
            ResultRecord.from_image_result(
                test_name=f"{self.test_location.nodeid}::{stem}",
                result=missing,
                results_root=collector.results_root,
            )
        )
        return success
