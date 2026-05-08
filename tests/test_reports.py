"""Integration tests for HTML/JSON report generation via pytester."""

from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

REPORT_TEST = textwrap.dedent("""\
    import matplotlib.pyplot as plt

    def test_one(snapshot_matplotlib):
        fig, ax = plt.subplots(); ax.plot([1, 2, 3])
        assert fig == snapshot_matplotlib

    def test_two(snapshot_matplotlib):
        fig, ax = plt.subplots(); ax.plot([1, 2, 4])
        assert fig == snapshot_matplotlib
""")


def test_html_report_generated(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(test_plots=REPORT_TEST)
    pytester.runpytest("--snapshot-update")

    pytester.runpytest("--snapshot-matplotlib-report=html", "-v").assert_outcomes(
        passed=2
    )

    report_dir = pytester.path / "figure-report"
    html = report_dir / "report.html"
    assert html.exists()
    assert "test_one" in html.read_text()


def test_basic_html_report_generated(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(test_plots=REPORT_TEST)
    pytester.runpytest("--snapshot-update")

    pytester.runpytest("--snapshot-matplotlib-report=basic-html", "-v").assert_outcomes(
        passed=2
    )

    report_dir = pytester.path / "figure-report"
    assert (report_dir / "report-basic.html").exists()


def test_json_report_generated(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(test_plots=REPORT_TEST)
    pytester.runpytest("--snapshot-update")

    pytester.runpytest("--snapshot-matplotlib-report=json", "-v").assert_outcomes(
        passed=2
    )

    report_dir = pytester.path / "figure-report"
    report = report_dir / "results.json"
    assert report.exists()
    data = json.loads(report.read_text())
    assert data["summary"]["total"] == 2
    assert data["summary"]["passed"] == 2


def test_all_report_types_together(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(test_plots=REPORT_TEST)
    pytester.runpytest("--snapshot-update")
    pytester.runpytest(
        "--snapshot-matplotlib-report=html,basic-html,json", "-v"
    ).assert_outcomes(passed=2)

    report_dir = pytester.path / "figure-report"
    assert (report_dir / "report.html").exists()
    assert (report_dir / "report-basic.html").exists()
    assert (report_dir / "results.json").exists()


def test_no_report_flag_all_pass_leaves_no_dir(pytester: pytest.Pytester) -> None:
    """No `--snapshot-matplotlib-report`: an all-pass run leaves no `figure-report/`."""
    pytester.makepyfile(test_plots=REPORT_TEST)
    pytester.runpytest("--snapshot-update")

    pytester.runpytest("-v").assert_outcomes(passed=2)

    assert not (pytester.path / "figure-report").exists()


def test_no_report_flag_failure_keeps_artifacts(pytester: pytest.Pytester) -> None:
    """No `--snapshot-matplotlib-report`: failures still write actual+baseline+diff."""
    pytester.makepyfile(test_plots=REPORT_TEST)
    pytester.runpytest("--snapshot-update")

    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt

            def test_one(snapshot_matplotlib):
                fig, ax = plt.subplots(); ax.plot([3, 2, 1])  # changed
                assert fig == snapshot_matplotlib

            def test_two(snapshot_matplotlib):
                fig, ax = plt.subplots(); ax.plot([1, 2, 4])
                assert fig == snapshot_matplotlib
        """)
    )
    pytester.runpytest("-v").assert_outcomes(failed=1, passed=1)

    report_dir = pytester.path / "figure-report"
    pngs = {p.name for p in report_dir.rglob("*.png")}
    assert "test_one.png" in pngs
    assert "test_one-expected.png" in pngs
    assert "test_one-diff.png" in pngs
    # test_two passed — no leftover artifacts for it.
    assert "test_two.png" not in pngs


def test_report_includes_failure(pytester: pytest.Pytester) -> None:
    """Failures are surfaced in the JSON report."""
    pytester.makepyfile(test_plots=REPORT_TEST)
    pytester.runpytest("--snapshot-update")

    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt

            def test_one(snapshot_matplotlib):
                fig, ax = plt.subplots(); ax.plot([3, 2, 1])  # changed
                assert fig == snapshot_matplotlib

            def test_two(snapshot_matplotlib):
                fig, ax = plt.subplots(); ax.plot([1, 2, 4])
                assert fig == snapshot_matplotlib
        """)
    )
    pytester.runpytest("--snapshot-matplotlib-report=json", "-v").assert_outcomes(
        failed=1, passed=1
    )

    report_dir = pytester.path / "figure-report"
    data = json.loads((report_dir / "results.json").read_text())
    assert data["summary"]["failed"] == 1
    assert data["summary"]["passed"] == 1


def test_auto_failed_only_html_report_on_failure(pytester: pytest.Pytester) -> None:
    """No flag + at least one failure → auto failed-only HTML report.

    Only the failed test is rendered; the passing test is omitted.
    """
    pytester.makepyfile(test_plots=REPORT_TEST)
    pytester.runpytest("--snapshot-update")

    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt

            def test_one(snapshot_matplotlib):
                fig, ax = plt.subplots(); ax.plot([3, 2, 1])  # changed
                assert fig == snapshot_matplotlib

            def test_two(snapshot_matplotlib):
                fig, ax = plt.subplots(); ax.plot([1, 2, 4])
                assert fig == snapshot_matplotlib
        """)
    )
    pytester.runpytest("-v").assert_outcomes(failed=1, passed=1)

    report_dir = pytester.path / "figure-report"
    html = report_dir / "report.html"
    assert html.exists()
    assert (report_dir / "styles.css").exists()
    body = html.read_text()
    assert "test_one" in body
    assert "test_two" not in body


def test_auto_report_absent_when_all_pass(pytester: pytest.Pytester) -> None:
    """No flag + no failures → no auto report and no figure-report/ dir."""
    pytester.makepyfile(test_plots=REPORT_TEST)
    pytester.runpytest("--snapshot-update")

    pytester.runpytest("-v").assert_outcomes(passed=2)

    assert not (pytester.path / "figure-report").exists()


def test_auto_report_absent_under_snapshot_update(pytester: pytest.Pytester) -> None:
    """`--snapshot-update` never emits the auto failed-only report.

    Even when fresh baselines are being generated, no `report.html` is
    written: ``GENERATED`` records aren't real failures and the user is
    actively rewriting baselines.
    """
    pytester.makepyfile(test_plots=REPORT_TEST)
    pytester.runpytest("--snapshot-update").assert_outcomes(passed=2)

    assert not (pytester.path / "figure-report" / "report.html").exists()
