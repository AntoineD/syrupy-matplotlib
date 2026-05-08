"""Unit tests for `_comparison.py`."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt

from syrupy_matplotlib._comparison import run_comparison
from syrupy_matplotlib._types import ImageMatchStatus
from syrupy_matplotlib._types import is_passing

if TYPE_CHECKING:
    from pathlib import Path


def _png_bytes(data: list[float]) -> bytes:
    fig, ax = plt.subplots()
    ax.plot(data)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", metadata={"Software": None})
    plt.close(fig)
    return buf.getvalue()


def test_run_comparison_match(tmp_path: Path) -> None:
    png = _png_bytes([1, 2, 3])
    result = run_comparison(
        test_bytes=png,
        baseline_bytes=png,
        tolerance=2.0,
        diff_dir=tmp_path,
        stem="foo",
    )
    assert result.status == ImageMatchStatus.MATCH
    assert is_passing(result.status)


def test_run_comparison_diff(tmp_path: Path) -> None:
    png_a = _png_bytes([1, 2, 3])
    png_b = _png_bytes([3, 2, 1])
    result = run_comparison(
        test_bytes=png_a,
        baseline_bytes=png_b,
        tolerance=0.01,
        diff_dir=tmp_path,
        stem="foo",
    )
    assert result.status == ImageMatchStatus.DIFF
    assert not is_passing(result.status)
    assert result.rms is not None
    assert result.rms > 0
    assert result.diff_path is not None
    assert result.diff_path.exists()


def test_run_comparison_match_keep_on_match_false_unlinks_files(tmp_path: Path) -> None:
    png = _png_bytes([1, 2, 3])
    result = run_comparison(
        test_bytes=png,
        baseline_bytes=png,
        tolerance=0.0,
        diff_dir=tmp_path,
        stem="foo",
        keep_on_match=False,
    )
    assert result.status == ImageMatchStatus.MATCH
    assert result.actual_path is None
    assert result.baseline_path is None
    assert list(tmp_path.iterdir()) == []


def test_run_comparison_diff_keep_on_match_false_keeps_artifacts(
    tmp_path: Path,
) -> None:
    png_a = _png_bytes([1, 2, 3])
    png_b = _png_bytes([3, 2, 1])
    result = run_comparison(
        test_bytes=png_a,
        baseline_bytes=png_b,
        tolerance=0.01,
        diff_dir=tmp_path,
        stem="foo",
        keep_on_match=False,
    )
    assert result.status == ImageMatchStatus.DIFF
    assert result.actual_path is not None
    assert result.actual_path.exists()
    assert result.baseline_path is not None
    assert result.baseline_path.exists()
    assert result.diff_path is not None
    assert result.diff_path.exists()


def test_run_comparison_missing_baseline(tmp_path: Path) -> None:
    png = _png_bytes([1, 2, 3])
    result = run_comparison(
        test_bytes=png,
        baseline_bytes=None,
        tolerance=2.0,
        diff_dir=tmp_path,
        stem="foo",
    )
    assert result.status == ImageMatchStatus.MISSING
    assert not is_passing(result.status)
    assert result.error_message is not None
