"""JSON report generation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from ._reporting import ResultCollector

_REPORT_VERSION = 2


def generate_json_report(collector: ResultCollector, results_dir: Path) -> Path:
    """Write a versioned JSON report to `results_dir/results.json`.

    Output structure::

        {
            "metadata": {"version": 2, "generator": "syrupy-matplotlib"},
            "summary": {"total": N, "passed": N, "failed": N},
            "results": {
                "nodeid": {
                    "test_name": "...",
                    "image_status": "match|diff|missing|generated",
                    "passed": true,
                    "rms": null,
                    "tolerance": 2.0,
                    "result_image": "...",
                    "baseline_image": "...",
                    "diff_image": null,
                    "error_message": null
                },
                ...
            }
        }

    Args:
        collector: Accumulated test results for the session.
        results_dir: Directory where the report file is written.

    Returns:
        Path to the generated `results.json` file.
    """
    summary = collector.compute_summary()
    report = {
        "metadata": {
            "version": _REPORT_VERSION,
            "generator": "syrupy-matplotlib",
        },
        "summary": summary.to_dict(),
        "results": collector.to_serializable(),
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / "results.json"
    with out.open("w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    return out
