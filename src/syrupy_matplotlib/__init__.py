"""syrupy-matplotlib: matplotlib figure comparison as a syrupy extension."""

from __future__ import annotations

from ._assertion import MplSnapshotAssertion
from ._extension import MplFigureExtension
from ._params import SnapshotParams

__all__ = [
    "MplFigureExtension",
    "MplSnapshotAssertion",
    "SnapshotParams",
]
