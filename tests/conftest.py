"""Shared fixtures for syrupy-matplotlib tests."""

from __future__ import annotations

import os
from pathlib import Path

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


@pytest.fixture(autouse=True)
def isolate_from_outer_xdist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide this run's xdist identity from pytester subprocesses.

    ``--runpytest=subprocess`` spawns a plain ``python -m pytest`` that
    inherits ``os.environ``. When *this* suite runs under ``pytest -n``,
    ``PYTEST_XDIST_WORKER`` leaks into that subprocess and syrupy's
    ``is_xdist_worker()`` reads it as proof of a controller. It then publishes
    a worker report and returns the exit status untouched, skipping unused
    snapshot detection — so ``test_unused_snapshot_fails`` saw a green inner
    run and the whole suite only failed under ``-n``.

    The inner pytest is standalone; nothing collects its worker report.
    """
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)
