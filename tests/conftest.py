"""Shared fixtures for syrupy-matplotlib tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

pytest_plugins = ["pytester"]

# Force the headless Agg backend before matplotlib gets imported by any test
# (including pytester subprocesses, which inherit this env var). Without it,
# tests that touch `plt.figure()` at module scope blow up under CI / SSH with
# `_tkinter.TclError: no display name and no $DISPLAY environment variable`.
os.environ.setdefault("MPLBACKEND", "agg")


def pytest_configure(config: pytest.Config) -> None:
    """Propagate coverage to pytester subprocesses via ``COVERAGE_PROCESS_START``.

    ``--runpytest=subprocess`` spawns fresh Python processes that do not
    inherit the parent's coverage tracer. The ``coverage`` package ships a
    site ``.pth`` that calls ``coverage.process_startup()`` when this env
    var is set, so subprocesses start measuring on import.
    """
    if config.pluginmanager.hasplugin("_cov"):  # pragma: no branch
        os.environ.setdefault(
            "COVERAGE_PROCESS_START",
            str(Path(__file__).parent.parent / ".coveragerc"),
        )
