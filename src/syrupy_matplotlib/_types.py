"""Shared enums and immutable result dataclasses."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class ImageMatchStatus(str, enum.Enum):
    """Outcome of a single pixel-level image comparison."""

    MATCH = "match"
    """Images are within the RMS tolerance."""

    DIFF = "diff"
    """Images differ beyond the RMS tolerance."""

    MISSING = "missing"
    """Baseline image was not found on disk."""

    GENERATED = "generated"
    """Baseline was just written (update mode)."""


_PASSING: frozenset[ImageMatchStatus] = frozenset({
    ImageMatchStatus.MATCH,
    ImageMatchStatus.GENERATED,
})


def is_passing(status: ImageMatchStatus) -> bool:
    """Return whether *status* counts as a passing test outcome.

    Args:
        status: The image-match status to classify.

    Returns:
        `True` for `MATCH` and `GENERATED`, `False` for `DIFF` and `MISSING`.
    """
    return status in _PASSING


@dataclass(frozen=True, slots=True)
class ImageResult:
    """Immutable result of a single pixel-level image comparison."""

    status: ImageMatchStatus
    """Comparison outcome."""

    rms: float | None = None
    """Root-mean-square pixel difference, or `None` when the baseline is missing
    or image shapes differ."""

    tolerance: float | None = None
    """RMS threshold used for this comparison, or `None` when no comparison ran
    (e.g. update-mode `GENERATED`)."""

    actual_path: Path | None = None
    """Path to the saved result image, or `None` when no artifact was written."""

    baseline_path: Path | None = None
    """Path to the baseline image, or `None` when missing."""

    diff_path: Path | None = None
    """Path to the generated diff image, or `None` when not produced."""

    error_message: str | None = None
    """Human-readable description of the failure, or `None` when comparison passed."""
