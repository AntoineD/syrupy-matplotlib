"""Test result data model and collection.

`ResultRecord` is the single source of truth for reporting — both JSON
and HTML reports are derived from it.  `ResultCollector` accumulates records
during a session and supports xdist serialization.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

from ._types import ImageMatchStatus
from ._types import is_passing

if TYPE_CHECKING:
    from pathlib import Path

    from ._types import ImageResult


@dataclass(frozen=True, slots=True)
class ResultRecord:
    """Complete result for one test item — immutable once handed to the collector."""

    test_name: str
    """Full pytest node id."""

    image_status: str | None = None
    """`ImageMatchStatus` value, or `None` when image comparison was not run."""

    rms: float | None = None
    """RMS pixel difference, or `None`."""

    tolerance: float | None = None
    """RMS tolerance used, or `None`."""

    result_image: str | None = None
    """Relative path to the result image from the results root, or `None`."""

    baseline_image: str | None = None
    """Relative path to the baseline image, or `None`."""

    diff_image: str | None = None
    """Relative path to the diff image, or `None`."""

    error_message: str | None = None
    """Human-readable failure description, or `None`."""

    @property
    def passed(self) -> bool:
        """Whether this record counts as a passing test outcome.

        Records with no `image_status` (e.g. pending) are treated as failed.

        Returns:
            `True` when `image_status` is `match` or `generated`.
        """
        if self.image_status is None:
            return False
        return is_passing(ImageMatchStatus(self.image_status))

    @classmethod
    def from_image_result(
        cls,
        test_name: str,
        result: ImageResult,
        results_root: Path | None = None,
    ) -> ResultRecord:
        """Build a `ResultRecord` from an `ImageResult`.

        Image paths are stored relative to *results_root* when provided so
        HTML reports can link to them portably.

        Args:
            test_name: Full pytest node id.
            result: Immutable result from the comparison engine.
            results_root: Root directory for result artifacts, used to compute
                relative paths.  Pass `None` to store absolute paths.

        Returns:
            A populated `ResultRecord`.
        """

        def _make_relpath(p: Path | None) -> str | None:
            if p is None:
                return None
            if results_root is None:
                return str(p)
            try:
                return p.relative_to(results_root).as_posix()
            except ValueError:
                return str(p)

        return cls(
            test_name=test_name,
            image_status=result.status.value,
            rms=result.rms,
            tolerance=result.tolerance,
            result_image=_make_relpath(result.actual_path),
            baseline_image=_make_relpath(result.baseline_path),
            diff_image=_make_relpath(result.diff_path),
            error_message=result.error_message,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary of all fields.

        Returns:
            Dictionary suitable for `json.dump()`.
        """
        d = asdict(self)
        d["passed"] = self.passed
        return d


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Aggregate statistics for a test run."""

    total: int = 0
    """Total number of records collected."""

    passed: int = 0
    """Number of passing tests."""

    failed: int = 0
    """Number of failing tests."""

    @classmethod
    def compute(cls, records: list[ResultRecord]) -> RunSummary:
        """Compute a `RunSummary` from a list of `ResultRecord` objects.

        Args:
            records: All records collected during the session.

        Returns:
            Populated `RunSummary`.
        """
        passed = 0
        failed = 0
        for r in records:
            if r.image_status is None:
                continue
            if r.passed:
                passed += 1
            else:
                failed += 1
        return cls(total=len(records), passed=passed, failed=failed)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary of all fields.

        Returns:
            Dictionary suitable for `json.dump()`.
        """
        return asdict(self)


class ResultCollector:
    """Accumulates `ResultRecord` objects during a pytest session.

    Supports xdist by serializing worker results to JSON and merging them on
    the controller.
    """

    results_root: Path | None
    """Root directory for result artifacts, used to compute relative image paths."""

    _records: dict[str, ResultRecord]
    """Internal mapping from node id to result record."""

    def __init__(self, results_root: Path | None = None) -> None:
        """Args:
        results_root: Root directory for result artifacts.  Pass `None`
            when no report directory is configured.
        """  # noqa: D205
        self._records = {}
        self.results_root = results_root

    def record(self, r: ResultRecord) -> None:
        """Add or replace the record for a test.

        Args:
            r: The `ResultRecord` to store, keyed by `r.test_name`.
        """
        self._records[r.test_name] = r

    @property
    def records(self) -> list[ResultRecord]:
        """All collected records in insertion order.

        Returns:
            List of `ResultRecord` objects.
        """
        return list(self._records.values())

    def compute_summary(self) -> RunSummary:
        """Compute aggregate statistics from all collected records.

        Returns:
            A `RunSummary` over the current set of records.
        """
        return RunSummary.compute(self.records)

    def to_serializable(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of all records.

        Returns:
            Mapping of node id to record dictionary.
        """
        return {name: rec.to_dict() for name, rec in self._records.items()}

    def merge_serialized(self, data: dict[str, Any]) -> None:
        """Merge results from a worker JSON blob (xdist).

        The `passed` key in each dict is recomputed from `image_status` on
        read, so it's stripped before reconstruction.

        Args:
            data: Dictionary produced by a worker's `to_serializable()`.
        """
        for name, rec_dict in data.items():
            payload = {k: v for k, v in rec_dict.items() if k != "passed"}
            self._records[name] = ResultRecord(**payload)

    def save_worker_json(self, path: Path) -> None:
        """Serialize all records to a JSON file (used by xdist workers).

        Args:
            path: Destination path; parent directories are created as needed.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            json.dump(self.to_serializable(), f, indent=2)
