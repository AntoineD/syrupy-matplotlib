"""pytest-xdist coordination for syrupy-matplotlib.

- Each worker publishes its `ResultCollector` records in
  `config.workeroutput` when its session finishes; xdist ships that mapping
  to the controller.
- The controller merges each worker's records as the worker goes down,
  before its own session finishes and writes the reports, and warns about
  every worker that went down without publishing them.
"""

from __future__ import annotations

import json
import warnings
from typing import TYPE_CHECKING
from typing import Any

import pytest

if TYPE_CHECKING:
    from ._reporting import ResultCollector


_WORKEROUTPUT_KEY = "syrupy_matplotlib_records"
"""Key of a worker's records in `config.workeroutput`."""


class XdistCoordinator:
    """Plugin registered on the xdist controller to gather the workers' records."""

    _collector: ResultCollector
    """The controller's collector, which the workers' records are merged into."""

    _lost_workers: list[str]
    """Ids of the workers that went down without publishing their records."""

    def __init__(self, collector: ResultCollector) -> None:
        """Args:
        collector: The controller's collector.
        """  # ruff: ignore[missing-blank-line-after-summary]
        self._collector = collector
        self._lost_workers = []

    def pytest_testnodedown(self, node: Any) -> None:
        """Merge a worker's records, or note that it died without publishing them.

        xdist calls this for every worker that goes down, cleanly or not, so
        a worker that crashed, ran out of memory or was killed by a timeout
        lands here too, with nothing published. Whether the records are
        there decides, not the hook's `error` argument: a worker interrupted
        by Ctrl-C finishes cleanly, then goes down a second time with an
        error.

        Args:
            node: The xdist `WorkerController` that went down.
        """
        payload = getattr(node, "workeroutput", {}).get(_WORKEROUTPUT_KEY)
        if payload is None:
            self._lost_workers.append(node.gateway.id)
        else:
            self._collector.merge_serialized(json.loads(payload))

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self) -> None:
        """Warn about each worker whose records never arrived.

        Not raised from `pytest_testnodedown`: xdist calls it from the test
        loop, where pytest captures no warnings, so the warning would miss
        the warnings summary. `trylast` lets the reports be written first,
        in case `-W error` turns the warning into an exception.
        """
        for worker_id in self._lost_workers:
            warnings.warn(
                f"syrupy-matplotlib: xdist worker {worker_id} died before "
                "handing over its results; any comparisons it ran are missing "
                "from the summary and reports.",
                stacklevel=1,
            )


def _is_worker(config: pytest.Config) -> bool:
    """Return ``True`` when *config* belongs to an xdist worker process."""
    return hasattr(config, "workerinput")


def publish_worker_results(config: pytest.Config, collector: ResultCollector) -> None:
    """Hand this worker's records to the controller.

    xdist ships `config.workeroutput` once every `pytest_sessionfinish`
    implementation has run, so this must be called from one. Called even
    with no records, since the controller takes a worker that published
    nothing for one that died.

    The records go as JSON text: execnet serializes only exact builtin
    types, while `to_serializable` promises JSON and nothing more.

    Args:
        config: The worker's pytest `Config`.
        collector: The worker's collector.
    """
    workeroutput: dict[str, Any] = config.workeroutput  # ty: ignore[unresolved-attribute]
    workeroutput[_WORKEROUTPUT_KEY] = json.dumps(collector.to_serializable())
