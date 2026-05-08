"""Tests for _reporting.py: data model and result collection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from syrupy_matplotlib._reporting import ResultCollector
from syrupy_matplotlib._reporting import ResultRecord
from syrupy_matplotlib._types import ImageMatchStatus
from syrupy_matplotlib._types import ImageResult


def _passed_result() -> ImageResult:
    return ImageResult(
        status=ImageMatchStatus.MATCH,
        tolerance=2.0,
        actual_path=Path("/tmp/result.png"),
        baseline_path=Path("/tmp/baseline.png"),
    )


def _failed_result() -> ImageResult:
    return ImageResult(
        status=ImageMatchStatus.DIFF,
        rms=12.3,
        tolerance=2.0,
        actual_path=Path("/tmp/result.png"),
        baseline_path=Path("/tmp/baseline.png"),
        diff_path=Path("/tmp/diff.png"),
        error_message="Images differ",
    )


def test_record_from_passed_result() -> None:
    record = ResultRecord.from_image_result("test::foo", _passed_result())
    assert record.test_name == "test::foo"
    assert record.passed is True
    assert record.image_status == "match"
    assert record.error_message is None


def test_record_from_failed_result() -> None:
    record = ResultRecord.from_image_result("test::bar", _failed_result())
    assert record.passed is False
    assert record.image_status == "diff"
    assert record.rms == pytest.approx(12.3)
    assert record.error_message == "Images differ"


def test_record_passed_false_when_image_status_missing() -> None:
    """Records without an `image_status` (e.g. pending) count as failed."""
    record = ResultRecord(test_name="t::pending")
    assert record.image_status is None
    assert record.passed is False


def test_collector_record_and_retrieve() -> None:
    collector = ResultCollector()
    r = ResultRecord.from_image_result("test::foo", _passed_result())
    collector.record(r)
    assert len(collector.records) == 1
    assert collector.records[0].test_name == "test::foo"


def test_collector_summary() -> None:
    collector = ResultCollector()
    collector.record(ResultRecord.from_image_result("t::a", _passed_result()))
    collector.record(ResultRecord.from_image_result("t::b", _failed_result()))
    # Pending records (no image_status) are counted in total but not classified.
    collector.record(ResultRecord(test_name="t::c"))

    summary = collector.compute_summary()
    assert summary.total == 3
    assert summary.passed == 1
    assert summary.failed == 1


def test_record_relpath_outside_results_root() -> None:
    """A result image outside the results root keeps its absolute path."""
    result = ImageResult(
        status=ImageMatchStatus.MATCH,
        tolerance=2.0,
        actual_path=Path("/elsewhere/result.png"),
        baseline_path=Path("/elsewhere/baseline.png"),
    )
    r = ResultRecord.from_image_result("t::a", result, results_root=Path("/somewhere"))
    # Falls back to absolute string when relative_to() raises ValueError.
    assert r.result_image == "/elsewhere/result.png"


def test_save_worker_json(tmp_path: Path) -> None:
    collector = ResultCollector()
    collector.record(ResultRecord.from_image_result("t::a", _passed_result()))
    out = tmp_path / "nested" / "fragment.json"
    collector.save_worker_json(out)
    data = json.loads(out.read_text())
    assert "t::a" in data


def test_collector_serialization_roundtrip() -> None:
    collector = ResultCollector()
    collector.record(ResultRecord.from_image_result("t::a", _passed_result()))

    serialized = collector.to_serializable()
    assert "t::a" in serialized
    assert serialized["t::a"]["passed"] is True

    collector2 = ResultCollector()
    collector2.merge_serialized(serialized)
    assert len(collector2.records) == 1
    assert collector2.records[0].test_name == "t::a"
    assert collector2.records[0].passed is True


def test_json_report(tmp_path: Path) -> None:
    from syrupy_matplotlib._json_report import generate_json_report

    collector = ResultCollector()
    collector.record(ResultRecord.from_image_result("t::a", _passed_result()))

    out = generate_json_report(collector, tmp_path)
    data = json.loads(out.read_text())

    assert data["metadata"]["version"] == 2
    assert data["summary"]["total"] == 1
    assert "t::a" in data["results"]
    assert data["results"]["t::a"]["passed"] is True
    assert data["results"]["t::a"]["image_status"] == "match"
