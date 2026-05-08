"""Pure comparison functions used by `MplFigureExtension.matches`.

`run_comparison()` writes diagnostic artifacts under *diff_dir* and returns
an immutable `ImageResult` that `_reporting.py` consumes.
"""

from __future__ import annotations

from pathlib import Path

from matplotlib.testing.compare import compare_images

from ._types import ImageMatchStatus
from ._types import ImageResult


def run_comparison(
    test_bytes: bytes,
    baseline_bytes: bytes | None,
    tolerance: float,
    diff_dir: Path,
    stem: str,
    ext: str = "png",
    keep_on_match: bool = True,
) -> ImageResult:
    """Compare a freshly-rendered figure against the stored baseline.

    Wraps `matplotlib.testing.compare.compare_images()` with an RMS
    tolerance. The actual + baseline blobs are written under *diff_dir*
    (`compare_images` reads them by path), and matplotlib's auto-generated
    diff PNG is renamed into place in the same directory.

    Args:
        test_bytes: Bytes freshly serialized from the test figure.
        baseline_bytes: Bytes loaded from the baseline, or `None` when no
            baseline exists on disk.
        tolerance: RMS threshold used for the comparison.
        diff_dir: Directory where result/baseline/diff artifacts are
            written. Created if absent.
        stem: Filename stem used for the copied artifacts (e.g.
            `test_multi.1`).
        ext: Image format extension without a leading dot.
        keep_on_match: When `False`, delete the actual and baseline blobs
            after a successful match so `figure-report/` only retains
            artifacts for failures.

    Returns:
        An `ImageResult` describing the outcome and any diagnostic paths
        for the HTML report.
    """
    diff_dir.mkdir(parents=True, exist_ok=True)
    actual_path = diff_dir / f"{stem}.{ext}"
    actual_path.write_bytes(test_bytes)

    if baseline_bytes is None:
        return ImageResult(
            status=ImageMatchStatus.MISSING,
            tolerance=tolerance,
            actual_path=actual_path,
            error_message="Baseline image not found on disk.",
        )

    baseline_path = diff_dir / f"{stem}-expected.{ext}"
    baseline_path.write_bytes(baseline_bytes)

    err = compare_images(
        str(baseline_path), str(actual_path), tol=tolerance, in_decorator=True
    )

    if err is None:
        if not keep_on_match:
            actual_path.unlink(missing_ok=True)
            baseline_path.unlink(missing_ok=True)
            return ImageResult(status=ImageMatchStatus.MATCH, tolerance=tolerance)
        return ImageResult(
            status=ImageMatchStatus.MATCH,
            tolerance=tolerance,
            actual_path=actual_path,
            baseline_path=baseline_path,
        )

    diff_dest: Path | None = None
    if err.get(
        "diff"
    ):  # pragma: no branch — matplotlib populates "diff" on a real failure
        diff_src = Path(str(err["diff"]))
        candidate = diff_dir / f"{stem}-diff.{ext}"
        try:
            diff_src.rename(candidate)
            diff_dest = candidate
        except OSError:  # pragma: no cover
            diff_dest = None

    return ImageResult(
        status=ImageMatchStatus.DIFF,
        rms=float(err["rms"]),
        tolerance=tolerance,
        actual_path=actual_path,
        baseline_path=baseline_path,
        diff_path=diff_dest,
        error_message=(
            f"Images differ (RMS {err['rms']:.3f} > tolerance {tolerance}):\n"
            f"  actual:   {actual_path}\n"
            f"  expected: {baseline_path}\n"
            f"  diff:     {diff_dest if diff_dest is not None else 'n/a'}"
        ),
    )
