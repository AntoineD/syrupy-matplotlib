"""Isolated unit tests for `_html_report.py` rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from syrupy_matplotlib._html_report import _compute_sort_key
from syrupy_matplotlib._html_report import generate_basic_html_report
from syrupy_matplotlib._html_report import generate_failed_only_html_report
from syrupy_matplotlib._html_report import generate_html_report
from syrupy_matplotlib._reporting import ResultCollector
from syrupy_matplotlib._reporting import ResultRecord
from syrupy_matplotlib._types import ImageMatchStatus


def _passing_record(name: str) -> ResultRecord:
    return ResultRecord(test_name=name, image_status=ImageMatchStatus.MATCH.value)


def _failing_record(name: str) -> ResultRecord:
    return ResultRecord(
        test_name=name,
        image_status=ImageMatchStatus.DIFF.value,
        rms=5.0,
        tolerance=2.0,
        error_message="rms 5.0 > 2.0",
    )


def _populated_collector() -> ResultCollector:
    c = ResultCollector(results_root=Path("/tmp/x"))
    c.record(_passing_record("test_a"))
    c.record(_failing_record("test_z"))
    c.record(_passing_record("test_m"))
    return c


def test_compute_sort_key_failures_first() -> None:
    """Failures sort before passes; ties break by test_name."""
    pass_a = _passing_record("test_a")
    pass_z = _passing_record("test_z")
    fail_m = _failing_record("test_m")
    ordered = sorted([pass_z, pass_a, fail_m], key=_compute_sort_key)
    assert [r.test_name for r in ordered] == ["test_m", "test_a", "test_z"]


def test_html_report_writes_html_and_css(tmp_path: Path) -> None:
    out = generate_html_report(_populated_collector(), tmp_path)
    assert out == tmp_path / "report.html"
    assert out.exists()
    assert (tmp_path / "styles.css").exists()
    body = out.read_text()
    assert "test_a" in body
    assert "test_z" in body


def test_html_report_failures_appear_before_passes(tmp_path: Path) -> None:
    out = generate_html_report(_populated_collector(), tmp_path)
    body = out.read_text()
    fail_pos = body.index("test_z")
    pass_a_pos = body.index("test_a")
    pass_m_pos = body.index("test_m")
    assert fail_pos < pass_a_pos
    assert fail_pos < pass_m_pos


def test_basic_html_report_no_external_assets(tmp_path: Path) -> None:
    out = generate_basic_html_report(_populated_collector(), tmp_path)
    assert out == tmp_path / "report-basic.html"
    assert out.exists()
    assert not (tmp_path / "styles.css").exists()


def test_html_report_creates_missing_dir(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "report"
    out = generate_html_report(_populated_collector(), target)
    assert out.exists()
    assert (target / "styles.css").exists()


@pytest.mark.parametrize(
    "generator",
    [generate_html_report, generate_basic_html_report],
)
def test_empty_collector_renders(tmp_path: Path, generator) -> None:
    """Empty collectors should still render without errors."""
    out = generator(ResultCollector(), tmp_path)
    assert out.exists()
    assert out.read_text()


def test_failed_only_html_report_excludes_passes(tmp_path: Path) -> None:
    """`generate_failed_only_html_report` renders only failed records.

    Summary numbers reflect the filtered subset: total == failed count,
    passed == 0.
    """
    out = generate_failed_only_html_report(_populated_collector(), tmp_path)
    assert out == tmp_path / "report.html"
    body = out.read_text()
    assert "test_z" in body
    assert "test_a" not in body
    assert "test_m" not in body
    assert "1 tests" in body
    assert ">1</strong> failed" in body
    assert ">0</strong> passed" in body
