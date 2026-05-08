"""The `snapshot_matplotlib` fixture — matplotlib-aware snapshot comparison.

Deliberately named distinctly from syrupy's built-in `snapshot`, so users can
use both fixtures side-by-side in the same test. Wraps the test body in a
`deterministic_context` and `plt.style.context` so figures are drawn under
reproducible settings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pytest
from matplotlib._pylab_helpers import Gcf
from syrupy.location import PyTestLocation

from ._assertion import MplSnapshotAssertion
from ._determinism import deterministic_context
from ._extension import MplFigureExtension
from ._params import SnapshotParams

if TYPE_CHECKING:
    from collections.abc import Generator

#: Stashed on `item.stash` so `pytest_runtest_call` can run auto-assertions
#: during the call phase. Populated only when the fixture is requested.
AUTO_STATE_KEY: pytest.StashKey[tuple[MplSnapshotAssertion, set[int]]] = (
    pytest.StashKey()
)


@pytest.fixture
def snapshot_matplotlib(
    request: pytest.FixtureRequest,
) -> Generator[MplSnapshotAssertion, None, None]:
    """Provide a matplotlib-aware snapshot assertion.

    The fixture sets a deterministic matplotlib environment (backend, font
    settings, ``SOURCE_DATE_EPOCH``) and activates the requested matplotlib
    style for the lifetime of the test, so figures drawn by the test are
    bit-identical across runs.

    Syrupy's built-in `snapshot` fixture is **not** shadowed — mix both in
    the same test freely::

        def test_mixed(snapshot, snapshot_matplotlib):
            assert {"k": 1} == snapshot  # syrupy amber
            fig, _ = plt.subplots()
            assert fig == snapshot_matplotlib  # this plugin

    Args:
        request: Pytest's fixture request object.

    Yields:
        A configured `MplSnapshotAssertion` usable with `==`.

    Raises:
        RuntimeError: If the `syrupy_matplotlib_plugin` is not registered
            on the pytest config (should not happen in normal use).
    """
    from ._plugin import Plugin

    plugin = request.config.pluginmanager.get_plugin("syrupy_matplotlib_plugin")
    if not isinstance(plugin, Plugin):  # pragma: no cover
        msg = "syrupy_matplotlib_plugin not registered"
        raise RuntimeError(msg)  # noqa: TRY004
    params = SnapshotParams.from_config(plugin.config)

    with (
        deterministic_context(params.backend),
        plt.style.context(params.style, after_reset=True),
    ):
        baseline_fig_nums = set(Gcf.figs)
        assertion = MplSnapshotAssertion(
            session=request.config._syrupy,  # ty: ignore[unresolved-attribute]
            extension_class=MplFigureExtension,
            test_location=PyTestLocation(request.node),
            update_snapshots=bool(request.config.option.update_snapshots),
            mpl_params=params,
            auto=plugin.config.auto,
        )
        request.node.stash[AUTO_STATE_KEY] = (assertion, baseline_fig_nums)
        try:
            yield assertion
        finally:
            close_auto_figures(assertion, baseline_fig_nums)


def collect_new_figures(baseline_fig_nums: set[int]) -> list:
    """Return figures opened after the fixture started, in number order.

    Args:
        baseline_fig_nums: Figure numbers that existed before fixture setup.

    Returns:
        Figures whose numbers are not in *baseline_fig_nums*.
    """
    return [
        Gcf.figs[num].canvas.figure
        for num in sorted(Gcf.figs)
        if num not in baseline_fig_nums
    ]


def close_auto_figures(
    assertion: MplSnapshotAssertion, baseline_fig_nums: set[int]
) -> None:
    """Close figures the fixture is responsible for, if auto mode is on.

    Runs during fixture teardown regardless of whether the test passed,
    so figures don't leak between tests.

    Args:
        assertion: The fixture's assertion object (carries `_mpl_auto`).
        baseline_fig_nums: Figure numbers that existed before fixture setup.
    """
    if not assertion._mpl_auto:
        return
    for fig in collect_new_figures(baseline_fig_nums):
        plt.close(fig)


def run_auto_assertions(item: pytest.Item) -> None:
    """Auto-assert any unasserted figure opened during *item* and fail on mismatch.

    Called from a `pytest_runtest_call` hookwrapper so a mismatch becomes a
    proper test failure (call phase) rather than a teardown error.

    Args:
        item: The pytest item being executed.

    Raises:
        RuntimeError: If the assertion was created with an unexpected
            extension type (should not happen in normal use).
    """
    state = item.stash.get(AUTO_STATE_KEY, None)
    if state is None:
        return
    assertion, baseline_fig_nums = state
    if not assertion._mpl_auto:
        return

    failures: list[str] = []
    for fig in collect_new_figures(baseline_fig_nums):
        if id(fig) in assertion._mpl_asserted_fig_ids:
            continue
        if fig == assertion:
            continue
        ext = assertion.extension
        if not isinstance(ext, MplFigureExtension):  # pragma: no cover
            msg = f"unexpected extension type: {type(ext).__name__}"
            raise RuntimeError(msg)  # noqa: TRY004
        msg = ext._mpl_last_failure_message or "figure mismatch"
        failures.append(f"figure #{fig.number}: {msg}")

    if failures:
        pytest.fail(
            "auto-assertion failed for figures:\n" + "\n".join(failures),
            pytrace=False,
        )
