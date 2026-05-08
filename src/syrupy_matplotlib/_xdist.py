"""pytest-xdist coordination for syrupy-matplotlib.

- The controller generates a unique session UID and forwards it to workers
  via `pytest_configure_node`.
- Each worker writes a JSON fragment of its `ResultCollector` on session
  end. The controller merges all fragments before generating reports.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


_UID_ATTR = "_syrupy_matplotlib_uid"


class XdistCoordinator:
    """Plugin registered on the xdist controller to propagate the session UID.

    The UID is sent to each worker node via `workerinput` so workers can
    name their fragment files in a way that won't collide with other
    sessions running in parallel.
    """

    def pytest_configure_node(self, node: object) -> None:
        """Populate `workerinput` before the worker process starts.

        Args:
            node: The xdist `WorkerController` node.
        """
        node.workerinput[  # ty: ignore[unresolved-attribute]
            "syrupy_matplotlib_uid"
        ] = getattr(
            node.config,  # ty: ignore[unresolved-attribute]
            _UID_ATTR,
            "main",
        )


def setup_session(config: pytest.Config) -> None:
    """Initialise xdist state during `pytest_sessionstart`.

    On the controller, a UUID is generated. On a worker, the UUID is read
    back from `workerinput`.

    Args:
        config: The pytest `Config` for the current process.
    """
    if _is_worker(config):
        workerinput: dict[str, str] = config.workerinput  # ty: ignore[unresolved-attribute]
        setattr(config, _UID_ATTR, workerinput["syrupy_matplotlib_uid"])
    else:
        setattr(config, _UID_ATTR, uuid.uuid4().hex)


def get_uid(config: pytest.Config) -> str:
    """Return the session UID stored on *config*.

    Args:
        config: The pytest `Config` for the current process.

    Returns:
        Hex UUID string, or `"main"` when xdist is not active.
    """
    return str(getattr(config, _UID_ATTR, "main"))


def _is_worker(config: pytest.Config) -> bool:
    """Return ``True`` when *config* belongs to an xdist worker process."""
    return hasattr(config, "workerinput")


def get_worker_id() -> str:
    """Return the xdist worker id for the current process.

    Returns:
        Worker id string (e.g. `"gw0"`), or `"main"` outside xdist.
    """
    return os.environ.get("PYTEST_XDIST_WORKER", "main")


def merge_worker_fragments(results_dir: Path, uid: str) -> dict[str, Any]:
    """Read and merge all per-worker result fragments, then delete them.

    Args:
        results_dir: Directory containing the fragment files.
        uid: Session UID used to glob the correct files.

    Returns:
        Merged mapping from record key to record dictionary.
    """
    merged: dict[str, Any] = {}
    for path in sorted(results_dir.glob(f"_results-{uid}-*.json")):
        with path.open() as f:
            merged.update(json.load(f))
        path.unlink()
    return merged
