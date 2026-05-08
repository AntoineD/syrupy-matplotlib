"""HTML report generation using Jinja2.

Self-contained output — no CDN dependencies.  The CSS file is copied
alongside the HTML so the report works offline and in CI artifact viewers.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment
from jinja2 import PackageLoader
from jinja2 import select_autoescape

from ._reporting import RunSummary

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._reporting import ResultCollector
    from ._reporting import ResultRecord


def _compute_sort_key(record: ResultRecord) -> tuple[int, str]:
    """Return a sort key that places failures first, then sorts by name.

    Args:
        record: A `ResultRecord` instance.

    Returns:
        `(priority, test_name)` tuple where failures have priority `0`.
    """
    priority = 1 if record.passed else 0
    return priority, record.test_name


def _render(
    template_name: str,
    collector: ResultCollector,
    *,
    records_filter: Callable[[ResultRecord], bool] | None = None,
) -> str:
    """Render *template_name* against the collector's summary and records.

    Args:
        template_name: Jinja template filename in the package's
            ``templates/`` directory.
        collector: Accumulated test results for the session.
        records_filter: Optional predicate; when given, only records for
            which it returns ``True`` are rendered, and the summary is
            recomputed from that subset.

    Returns:
        Rendered HTML.
    """
    env = Environment(
        loader=PackageLoader("syrupy_matplotlib", "templates"),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(template_name)
    if records_filter is None:
        records = sorted(collector.records, key=_compute_sort_key)
        summary = collector.compute_summary()
    else:
        filtered = [r for r in collector.records if records_filter(r)]
        records = sorted(filtered, key=_compute_sort_key)
        summary = RunSummary.compute(filtered)
    return template.render(summary=summary, records=records)


def generate_html_report(
    collector: ResultCollector,
    results_dir: Path,
    *,
    records_filter: Callable[[ResultRecord], bool] | None = None,
) -> Path:
    """Generate `results_dir/report.html` plus `results_dir/styles.css`.

    Failures are sorted to the top of the report.  The CSS is copied from the
    package templates directory so the output is self-contained.

    Args:
        collector: Accumulated test results for the session.
        results_dir: Directory where the report files are written.
        records_filter: Optional predicate restricting the report to a
            subset of records (summary recomputed accordingly).

    Returns:
        Path to the generated `report.html` file.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / "report.html"
    out.write_text(
        _render("report.html.jinja2", collector, records_filter=records_filter),
        encoding="utf-8",
    )

    css_src = Path(__file__).parent / "templates" / "styles.css"
    shutil.copy2(css_src, results_dir / "styles.css")

    return out


def generate_failed_only_html_report(
    collector: ResultCollector, results_dir: Path
) -> Path:
    """Generate an HTML report containing only failed records.

    Args:
        collector: Accumulated test results for the session.
        results_dir: Directory where the report files are written.

    Returns:
        Path to the generated `report.html` file.
    """
    return generate_html_report(
        collector, results_dir, records_filter=lambda r: not r.passed
    )


def generate_basic_html_report(collector: ResultCollector, results_dir: Path) -> Path:
    """Generate `results_dir/report-basic.html` — a simple standalone table.

    No external assets are required; all styling is inlined by the template.

    Args:
        collector: Accumulated test results for the session.
        results_dir: Directory where the report file is written.

    Returns:
        Path to the generated `report-basic.html` file.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / "report-basic.html"
    out.write_text(_render("basic.html.jinja2", collector), encoding="utf-8")
    return out
