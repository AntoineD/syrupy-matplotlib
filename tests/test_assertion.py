"""Unit tests for `_assertion.py`."""

from __future__ import annotations

from unittest.mock import MagicMock

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
