"""Implementation of the `snapshot_matplotlib` fixture.

The fixture itself is declared in `_plugin` (pytest discovers it on the
entry-point module) as a thin wrapper that imports this module lazily —
this module pulls in matplotlib and syrupy, which must not load at pytest
startup for suites that never use the fixture.

The fixture is deliberately named distinctly from syrupy's built-in
`snapshot`, so users can use both side-by-side in the same test. It wraps
the test body in a `deterministic_context` and `plt.style.context` so
figures are drawn under reproducible settings.
"""

from __future__ import annotations

import warnings
import weakref
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pytest
from matplotlib._pylab_helpers import Gcf
from syrupy.location import PyTestLocation

from ._assertion import MplSnapshotAssertion
from ._determinism import deterministic_context
from ._extension import MplFigureExtension
from ._params import SnapshotParams
from ._plugin import AUTO_STATE_KEY
from ._plugin import Plugin

if TYPE_CHECKING:
    from collections.abc import Generator

    from matplotlib.figure import Figure


def generate_snapshot_assertion(
    request: pytest.FixtureRequest,
) -> Generator[MplSnapshotAssertion, None, None]:
    """Provide a matplotlib-aware snapshot assertion (fixture body).

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
    plugin = request.config.pluginmanager.get_plugin("syrupy_matplotlib_plugin")
    if not isinstance(plugin, Plugin):  # pragma: no cover
        msg = "syrupy_matplotlib_plugin not registered"
        raise RuntimeError(msg)  # ruff: ignore[type-check-without-type-error]
    plugin.bind_extension_class()
    params = SnapshotParams.from_config(plugin.config)

    with (
        # A list, not the tuple: matplotlib only treats a non-str, non-Path,
        # non-mapping argument as a sequence of styles to compose.
        plt.style.context(list(params.style), after_reset=True),
        deterministic_context(params.backend),
    ):
        # Weak, and by object rather than figure number: matplotlib hands a
        # new figure `max(live numbers) + 1`, so closing a pre-existing
        # figure recycles its number and a number set would treat the
        # newcomer as pre-existing — silently exempt from auto-assert and
        # auto-close.
        baseline_figs: weakref.WeakSet[Figure] = weakref.WeakSet(
            manager.canvas.figure for manager in Gcf.figs.values()
        )
        assertion = MplSnapshotAssertion(
            session=request.config._syrupy,  # ty: ignore[unresolved-attribute]
            extension_class=MplFigureExtension,
            test_location=PyTestLocation(request.node),
            update_snapshots=bool(request.config.option.update_snapshots),
            mpl_params=params,
            auto=plugin.config.auto,
        )
        request.node.stash[AUTO_STATE_KEY] = (assertion, baseline_figs)
        try:
            yield assertion
        finally:
            close_auto_figures(assertion, baseline_figs)


def collect_new_figures(baseline_figs: weakref.WeakSet[Figure]) -> list[Figure]:
    """Return figures opened after the fixture started, in number order.

    Membership is by figure object, not figure number — a number can be
    recycled within the test (see the comment at the `WeakSet` creation),
    while a live object cannot.

    Args:
        baseline_figs: Figures that existed before fixture setup.

    Returns:
        Figures not in *baseline_figs*.
    """
    return [
        manager.canvas.figure
        for _, manager in sorted(Gcf.figs.items())
        if manager.canvas.figure not in baseline_figs
    ]


def close_auto_figures(
    assertion: MplSnapshotAssertion, baseline_figs: weakref.WeakSet[Figure]
) -> None:
    """Close figures the fixture is responsible for, if auto mode is on.

    Runs during fixture teardown regardless of whether the test passed,
    so figures don't leak between tests.

    Args:
        assertion: The fixture's assertion object (carries `_mpl_auto`).
        baseline_figs: Figures that existed before fixture setup.
    """
    if not assertion._mpl_auto:
        return
    for fig in collect_new_figures(baseline_figs):
        plt.close(fig)


def run_auto_assertions(item: pytest.Item) -> None:
    """Auto-assert any unasserted figure opened during *item* and fail on mismatch.

    Called from a `pytest_runtest_call` hookwrapper so a mismatch becomes a
    proper test failure (call phase) rather than a teardown error. The
    hookwrapper only calls this when `AUTO_STATE_KEY` is stashed on *item*,
    i.e. when the fixture ran for this test.

    Args:
        item: The pytest item being executed.

    Raises:
        RuntimeError: If the assertion was created with an unexpected
            extension type (should not happen in normal use).
    """
    assertion, baseline_figs = item.stash[AUTO_STATE_KEY]
    if not assertion._mpl_auto:
        return

    new_figures = collect_new_figures(baseline_figs)
    if not new_figures and not assertion._mpl_asserted_figs:
        _warn_nothing_compared(item)
        return

    failures: list[str] = []
    for fig in new_figures:
        if fig in assertion._mpl_asserted_figs:
            continue
        if fig == assertion:
            continue
        ext = assertion.extension
        if not isinstance(ext, MplFigureExtension):  # pragma: no cover
            msg = f"unexpected extension type: {type(ext).__name__}"
            raise RuntimeError(msg)  # ruff: ignore[type-check-without-type-error]
        failures.append(f"figure #{fig.number}: {_describe_failure(assertion, ext)}")

    if failures:
        pytest.fail(
            "auto-assertion failed for figures:\n" + "\n".join(failures),
            pytrace=False,
        )


def _describe_failure(assertion: MplSnapshotAssertion, ext: MplFigureExtension) -> str:
    """Return the text explaining why the assertion that just ran failed.

    Syrupy's `_assert` catches every exception and returns `False`, so a
    serialization error — a rejected `savefig_kwargs`, a backend that cannot
    render — arrives here indistinguishable from a pixel mismatch. In that
    case `matches()` never ran and left no comparison message, and reporting
    the fallback would tell the user "figure mismatch" for a figure that was
    never compared. The explicit `assert fig == snapshot_matplotlib` path
    surfaces the traceback through syrupy's own diff; the auto path has to
    read it off the execution record.

    `_execution_results` and `_executions` are syrupy private API, covered by
    the same `syrupy>=5.1,<6` pin that `_assertion._assert` relies on.

    Args:
        assertion: The fixture's assertion object.
        ext: The stamped extension instance.

    Returns:
        The exception text when the assertion raised, otherwise the message
        `matches()` recorded for the failed comparison.
    """
    latest = assertion._execution_results.get(assertion._executions - 1)
    if latest is not None and latest.exception is not None:
        return f"{type(latest.exception).__name__}: {latest.exception}"
    return ext._mpl_last_failure_message or "figure mismatch"


def _warn_nothing_compared(item: pytest.Item) -> None:
    """Warn that a test requested the fixture but compared no figure.

    Auto-discovery reads `matplotlib._pylab_helpers.Gcf`, which only knows
    about pyplot-managed figures. A figure built as `Figure()` — the usual
    shape for embedded or library code — is invisible to it, so a test that
    never asserts explicitly passes without comparing anything at all.
    Silence there is indistinguishable from a green run.

    Args:
        item: The pytest item being executed.
    """
    warnings.warn(
        f"{item.nodeid}: snapshot_matplotlib compared no figure. Auto-discovery "
        "only sees pyplot-managed figures (plt.figure/plt.subplots); assert a "
        "bare Figure() explicitly with `assert fig == snapshot_matplotlib`, or "
        "pass `auto=False` if the test intentionally compares nothing.",
        stacklevel=1,
    )
