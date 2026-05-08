"""Tests for _params.py: SnapshotParams defaults and merging."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syrupy_matplotlib._config import Config
from syrupy_matplotlib._config import resolve_config
from syrupy_matplotlib._params import SnapshotParams

if TYPE_CHECKING:
    import pytest


def _cfg(
    tolerance: float = 2.0,
    *,
    remove_text: bool = False,
    savefig_kwargs: dict | None = None,
) -> Config:
    return Config(
        report=frozenset(),
        tolerance=tolerance,
        style="classic",
        backend="agg",
        auto=True,
        remove_text=remove_text,
        savefig_kwargs=savefig_kwargs if savefig_kwargs is not None else {},
    )


def test_from_config_defaults() -> None:
    params = SnapshotParams.from_config(_cfg())
    assert params.tolerance == 2.0
    assert params.style == "classic"
    assert params.backend == "agg"
    assert params.remove_text is False
    assert params.savefig_kwargs == {}


def test_merge_overrides() -> None:
    base = SnapshotParams.from_config(_cfg())
    merged = base.merge(tolerance=10.0, remove_text=True)
    assert merged.tolerance == 10.0
    assert merged.remove_text is True
    # Base is untouched (frozen dataclass)
    assert base.tolerance == 2.0
    assert base.remove_text is False


def test_merge_no_op() -> None:
    base = SnapshotParams.from_config(_cfg())
    merged = base.merge()
    assert merged == base


def test_merge_savefig_kwargs_replaces() -> None:
    base = SnapshotParams.from_config(_cfg())
    merged = base.merge(savefig_kwargs={"dpi": 200})
    assert merged.savefig_kwargs == {"dpi": 200}


def test_resolve_config_defaults(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]")
    config = pytester.parseconfigure()
    cfg = resolve_config(config)
    params = SnapshotParams.from_config(cfg)
    assert params.tolerance == 0.0


def test_from_config_propagates_remove_text_and_savefig() -> None:
    cfg = _cfg(remove_text=True, savefig_kwargs={"dpi": 300})
    params = SnapshotParams.from_config(cfg)
    assert params.remove_text is True
    assert params.savefig_kwargs == {"dpi": 300}


def test_from_config_savefig_kwargs_is_copied() -> None:
    """Ensure mutations on params.savefig_kwargs do not leak into Config."""
    config_dict = {"dpi": 100}
    cfg = _cfg(savefig_kwargs=config_dict)
    params = SnapshotParams.from_config(cfg)
    params.savefig_kwargs["dpi"] = 999
    assert config_dict == {"dpi": 100}
