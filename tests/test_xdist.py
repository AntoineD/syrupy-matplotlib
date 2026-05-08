"""Unit tests for `_xdist.py`."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from syrupy_matplotlib._xdist import XdistCoordinator
from syrupy_matplotlib._xdist import _is_worker
from syrupy_matplotlib._xdist import get_uid
from syrupy_matplotlib._xdist import get_worker_id
from syrupy_matplotlib._xdist import merge_worker_fragments
from syrupy_matplotlib._xdist import setup_session

if TYPE_CHECKING:
    from pathlib import Path


def _controller_config() -> MagicMock:
    return MagicMock(spec=[])
    # No workerinput → controller


def _worker_config(uid: str) -> MagicMock:
    cfg = MagicMock(spec=["workerinput"])
    cfg.workerinput = {"syrupy_matplotlib_uid": uid}
    return cfg


def test_setup_session_controller_generates_uid() -> None:
    cfg = _controller_config()
    setup_session(cfg)
    assert get_uid(cfg) != "main"


def test_setup_session_worker_reads_workerinput() -> None:
    cfg = _worker_config("abc123")
    setup_session(cfg)
    assert get_uid(cfg) == "abc123"


def test_get_uid_defaults_to_main() -> None:
    cfg = MagicMock(spec=[])
    assert get_uid(cfg) == "main"


def test_is_worker_detects_workerinput() -> None:
    assert _is_worker(_worker_config("x")) is True
    assert _is_worker(_controller_config()) is False


def test_worker_id_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw2")
    assert get_worker_id() == "gw2"


def test_worker_id_default(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    assert get_worker_id() == "main"


def test_coordinator_populates_workerinput() -> None:
    node = SimpleNamespace(
        workerinput={},
        config=SimpleNamespace(_syrupy_matplotlib_uid="abc"),
    )
    XdistCoordinator().pytest_configure_node(node)
    assert node.workerinput["syrupy_matplotlib_uid"] == "abc"


def test_merge_worker_fragments_combines_and_deletes(tmp_path: Path) -> None:
    uid = "u1"
    (tmp_path / f"_results-{uid}-gw0.json").write_text(
        json.dumps({"a": {"test_name": "a"}})
    )
    (tmp_path / f"_results-{uid}-gw1.json").write_text(
        json.dumps({"b": {"test_name": "b"}})
    )

    merged = merge_worker_fragments(tmp_path, uid)
    assert set(merged) == {"a", "b"}
    # Fragments cleaned up
    assert not any(tmp_path.glob(f"_results-{uid}-*.json"))


def test_merge_worker_fragments_empty(tmp_path: Path) -> None:
    assert merge_worker_fragments(tmp_path, "nonexistent") == {}


def test_setup_session_controller_has_unique_uid() -> None:
    cfg1 = _controller_config()
    cfg2 = _controller_config()
    setup_session(cfg1)
    setup_session(cfg2)
    assert get_uid(cfg1) != get_uid(cfg2)
