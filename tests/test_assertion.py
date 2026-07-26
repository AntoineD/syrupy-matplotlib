"""Unit tests for `_assertion.py`."""

from __future__ import annotations

import gc
from unittest.mock import MagicMock

import matplotlib.pyplot as plt
import pytest

from syrupy_matplotlib._assertion import MplSnapshotAssertion
from syrupy_matplotlib._extension import MplFigureExtension
from syrupy_matplotlib._params import SnapshotParams


def _make_assertion(pytester: pytest.Pytester) -> MplSnapshotAssertion:
    # Spin up a lightweight session via pytester so syrupy's SnapshotSession
    # is real.
    from syrupy.location import PyTestLocation
    from syrupy.session import SnapshotSession

    pytester.makepyfile(test_dummy="def test_it(): pass")
    config = pytester.parseconfigure()
    session = MagicMock(spec=[])
    session.config = config
    session.config.option.warn_unused_snapshots = False
    session.config.option.update_snapshots = False
    syrupy_session = SnapshotSession(pytest_session=session)

    item = MagicMock()
    item.name = "test_it"
    item.path = pytester.path / "test_dummy.py"
    item.obj = lambda: None
    item.obj.__module__ = "test_dummy"
    item.obj.__name__ = "test_it"
    item.nodeid = "test_dummy.py::test_it"

    return MplSnapshotAssertion(
        session=syrupy_session,
        extension_class=MplFigureExtension,
        test_location=PyTestLocation(item),
        update_snapshots=False,
        mpl_params=SnapshotParams(
            tolerance=2.0,
            style="classic",
            backend="agg",
            remove_text=False,
        ),
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"matcher": lambda **_: None},
        {"diff": 0},
        {"exclude": lambda **_: False},
        {"include": lambda **_: True},
        {"extension_class": MplFigureExtension},
    ],
    ids=["matcher", "diff", "exclude", "include", "extension_class"],
)
def test_call_forwards_syrupy_kwargs(pytester: pytest.Pytester, kwargs: dict) -> None:
    """Each syrupy-native kwarg passes straight through to the parent."""
    snap = _make_assertion(pytester)
    assert snap(**kwargs) is snap


def test_call_stores_mpl_overrides(pytester: pytest.Pytester) -> None:
    snap = _make_assertion(pytester)
    snap(tolerance=10.0, remove_text=True)
    assert snap._mpl_params.tolerance == 10.0
    assert snap._mpl_params.remove_text is True


def test_call_override_reverts_after_post_assert(pytester: pytest.Pytester) -> None:
    """A per-call override is undone by syrupy's post-assert cleanup.

    `__call__` stashes the override on `self` and registers a revert in
    `_post_assert_actions`; syrupy drains those after each assertion. Simulate
    that drain and confirm `_mpl_params` returns to the fixture default, so the
    override cannot leak into a later assertion in the same test.
    """
    snap = _make_assertion(pytester)
    assert snap._mpl_params.tolerance == 2.0

    snap(tolerance=99.0)
    assert snap._mpl_params.tolerance == 99.0

    snap._post_assert()
    assert snap._mpl_params.tolerance == 2.0


def test_set_defaults_survives_post_assert(pytester: pytest.Pytester) -> None:
    """`set_defaults` rebinds the fixture params, so the drain doesn't undo it."""
    snap = _make_assertion(pytester)

    assert snap.set_defaults(tolerance=99.0, remove_text=True, auto=False) is snap
    snap._post_assert()

    assert snap._mpl_params.tolerance == 99.0
    assert snap._mpl_params.remove_text is True
    assert snap._mpl_auto is False


def test_set_defaults_no_args_keeps_params(pytester: pytest.Pytester) -> None:
    """Every argument is optional; omitting all of them changes nothing."""
    snap = _make_assertion(pytester)
    snap.set_defaults()
    assert snap._mpl_params.tolerance == 2.0
    assert snap._mpl_auto is True


def test_set_defaults_savefig_kwargs_replaces(pytester: pytest.Pytester) -> None:
    """`savefig_kwargs` replaces wholesale, matching `merge()`."""
    snap = _make_assertion(pytester)
    snap.set_defaults(savefig_kwargs={"dpi": 150})
    assert snap._mpl_params.savefig_kwargs == {"dpi": 150}


def test_asserted_figs_entry_dies_with_the_figure(pytester: pytest.Pytester) -> None:
    """Closed figures drop out of the asserted set.

    With a plain `id()` set, a new figure allocated at a dead figure's
    address would be treated as already asserted and silently skipped by
    the auto path. Weak tracking removes the entry as soon as the figure
    is garbage collected.
    """
    snap = _make_assertion(pytester)
    fig = plt.figure()
    snap._mpl_asserted_figs.add(fig)
    assert fig in snap._mpl_asserted_figs

    plt.close(fig)
    del fig
    gc.collect()
    assert len(snap._mpl_asserted_figs) == 0


def test_call_auto_override_persists_across_post_assert(
    pytester: pytest.Pytester,
) -> None:
    """`auto` is deliberately not reverted — it governs once-per-test teardown."""
    snap = _make_assertion(pytester)
    assert snap._mpl_auto is True

    snap(auto=False)
    assert snap._mpl_auto is False

    snap._post_assert()
    assert snap._mpl_auto is False


def test_describe_failure_falls_back_without_an_execution(
    pytester: pytest.Pytester,
) -> None:
    """No execution recorded yet → the comparison message is the only source."""
    from syrupy_matplotlib._fixture import _describe_failure

    snap = _make_assertion(pytester)
    ext = MplFigureExtension()
    ext._mpl_last_failure_message = "Images differ (RMS 3.000 > tolerance 0.0)"

    assert _describe_failure(snap, ext) == "Images differ (RMS 3.000 > tolerance 0.0)"
