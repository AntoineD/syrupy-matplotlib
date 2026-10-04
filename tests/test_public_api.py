"""Validate the package's public import surface."""

from __future__ import annotations

import syrupy_matplotlib


def test_all_names_resolve() -> None:
    """Every name in __all__ must be importable from the top-level package."""
    for name in syrupy_matplotlib.__all__:
        assert hasattr(syrupy_matplotlib, name), (
            f"{name} missing from package namespace"
        )


def test_all_matches_documented_exports() -> None:
    """Sanity: __all__ matches the three documented public types."""
    assert set(syrupy_matplotlib.__all__) == {
        "MplFigureExtension",
        "MplSnapshotAssertion",
        "SnapshotParams",
    }


def test_dir_advertises_lazy_exports() -> None:
    """`dir()` must list the lazy exports without importing them (PEP 562)."""
    listed = dir(syrupy_matplotlib)
    for name in syrupy_matplotlib.__all__:
        assert name in listed


def test_public_types_are_classes() -> None:
    """Each public export is a class users can subclass or instantiate."""
    from syrupy_matplotlib import MplFigureExtension
    from syrupy_matplotlib import MplSnapshotAssertion
    from syrupy_matplotlib import SnapshotParams

    assert isinstance(MplFigureExtension, type)
    assert isinstance(MplSnapshotAssertion, type)
    assert isinstance(SnapshotParams, type)
