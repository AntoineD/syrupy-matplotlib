"""syrupy-matplotlib: matplotlib figure comparison as a syrupy extension."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from ._assertion import MplSnapshotAssertion
    from ._extension import MplFigureExtension
    from ._params import SnapshotParams

__all__ = [
    "MplFigureExtension",
    "MplSnapshotAssertion",
    "SnapshotParams",
]


def __getattr__(name: str) -> Any:
    """Resolve public exports on first access (PEP 562).

    The package `__init__` runs on every pytest startup (the plugin entry
    point lives in a submodule), and eager re-exports would drag in
    matplotlib and syrupy — several hundred milliseconds — for suites that
    never touch a figure.

    Args:
        name: Attribute requested on the package.

    Returns:
        The resolved public class.

    Raises:
        AttributeError: If *name* is not a public export.
    """
    lazy_exports = {
        "MplFigureExtension": "_extension",
        "MplSnapshotAssertion": "_assertion",
        "SnapshotParams": "_params",
    }
    try:
        module_name = lazy_exports[name]
    except KeyError:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg) from None
    from importlib import import_module

    return getattr(import_module(f".{module_name}", __name__), name)
