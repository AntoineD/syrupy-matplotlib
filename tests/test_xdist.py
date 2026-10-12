"""Unit tests for `_xdist.py`."""

from __future__ import annotations

import warnings
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from syrupy_matplotlib._reporting import ResultCollector
from syrupy_matplotlib._reporting import ResultRecord
from syrupy_matplotlib._types import ImageMatchStatus
from syrupy_matplotlib._xdist import XdistCoordinator
from syrupy_matplotlib._xdist import _is_worker
from syrupy_matplotlib._xdist import publish_worker_results


def _controller_config() -> MagicMock:
    return MagicMock(spec=[])
    # No workerinput → controller


def _worker_config() -> MagicMock:
    cfg = MagicMock(spec=["workerinput", "workeroutput"])
    cfg.workerinput = {}
    cfg.workeroutput = {}
    return cfg


def _down_node(worker_id: str, **attrs: object) -> SimpleNamespace:
    """Mimic the parts of an xdist `WorkerController` the coordinator reads."""
    return SimpleNamespace(gateway=SimpleNamespace(id=worker_id), **attrs)


def test_is_worker_detects_workerinput() -> None:
    assert _is_worker(_worker_config()) is True
    assert _is_worker(_controller_config()) is False


def test_coordinator_merges_published_records() -> None:
    """What a worker publishes lands in the controller's collector.

    A worker interrupted by Ctrl-C is reported down twice — cleanly, then
    with an error — and must not be taken for one that died.
    """
    worker = ResultCollector()
    worker.record(ResultRecord("t::a", ImageMatchStatus.MATCH.value, tolerance=0.5))
    config = _worker_config()
    publish_worker_results(config, worker)
    controller = ResultCollector()
    coordinator = XdistCoordinator(controller)
    node = _down_node("gw0", workeroutput=config.workeroutput)

    coordinator.pytest_testnodedown(node)
    coordinator.pytest_testnodedown(node)

    assert controller.records == worker.records
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        coordinator.pytest_sessionfinish()


def test_coordinator_does_not_lose_worker_without_records() -> None:
    """A worker that ran no comparison still publishes, and is not lost."""
    config = _worker_config()
    publish_worker_results(config, ResultCollector())
    controller = ResultCollector()
    coordinator = XdistCoordinator(controller)

    coordinator.pytest_testnodedown(_down_node("gw0", workeroutput=config.workeroutput))

    assert controller.records == []
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        coordinator.pytest_sessionfinish()


@pytest.mark.parametrize(
    "attrs",
    [
        # Crashed: xdist never received the worker's "finished" event.
        {},
        # Finished without publishing, e.g. its session finish raised first.
        {"workeroutput": {"exitstatus": 1}},
    ],
)
def test_coordinator_warns_about_worker_that_never_published(
    attrs: dict[str, object],
) -> None:
    coordinator = XdistCoordinator(ResultCollector())

    coordinator.pytest_testnodedown(_down_node("gw3", **attrs))

    with pytest.warns(UserWarning, match="xdist worker gw3 died before handing over"):
        coordinator.pytest_sessionfinish()
