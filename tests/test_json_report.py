"""Isolated unit tests for `_json_report.py` rendering."""

from __future__ import annotations

import json
from pathlib import Path

from syrupy_matplotlib._json_report import generate_json_report
from syrupy_matplotlib._reporting import ResultCollector
from syrupy_matplotlib._reporting import ResultRecord
from syrupy_matplotlib._types import ImageMatchStatus


def _populated_collector() -> ResultCollector:
    c = ResultCollector(results_root=Path("/tmp/x"))
    c.record(
        ResultRecord(test_name="test_a", image_status=ImageMatchStatus.MATCH.value)
    )
    c.record(
        ResultRecord(
            test_name="test_b",
            image_status=ImageMatchStatus.DIFF.value,
            rms=5.0,
            tolerance=2.0,
            error_message="differs",
        )
    )
    return c


def test_json_report_path_and_filename(tmp_path: Path) -> None:
    out = generate_json_report(_populated_collector(), tmp_path)
    assert out == tmp_path / "results.json"
    assert out.exists()


def test_json_report_metadata_version(tmp_path: Path) -> None:
    out = generate_json_report(_populated_collector(), tmp_path)
    data = json.loads(out.read_text())
    assert data["metadata"]["version"] == 2
    assert data["metadata"]["generator"] == "syrupy-matplotlib"


def test_json_report_summary_counts(tmp_path: Path) -> None:
    out = generate_json_report(_populated_collector(), tmp_path)
    data = json.loads(out.read_text())
    assert data["summary"]["total"] == 2
    assert data["summary"]["passed"] == 1
    assert data["summary"]["failed"] == 1


def test_json_report_per_record_fields(tmp_path: Path) -> None:
    out = generate_json_report(_populated_collector(), tmp_path)
    data = json.loads(out.read_text())
    a = data["results"]["test_a"]
    b = data["results"]["test_b"]
    assert a["passed"] is True
    assert a["image_status"] == "match"
    assert b["passed"] is False
    assert b["rms"] == 5.0
    assert b["tolerance"] == 2.0
    assert b["error_message"] == "differs"


def test_json_report_creates_missing_dir(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "out"
    out = generate_json_report(_populated_collector(), target)
    assert out.exists()


def test_json_report_empty_collector(tmp_path: Path) -> None:
    out = generate_json_report(ResultCollector(), tmp_path)
    data = json.loads(out.read_text())
    assert data["summary"] == {"total": 0, "passed": 0, "failed": 0}
    assert data["results"] == {}
