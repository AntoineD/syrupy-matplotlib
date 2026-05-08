"""Unit tests for `_determinism.py`."""

from __future__ import annotations

import os

import matplotlib

from syrupy_matplotlib._determinism import deterministic_context


def test_context_sets_source_date_epoch() -> None:
    os.environ.pop("SOURCE_DATE_EPOCH", None)
    with deterministic_context("agg"):
        assert os.environ["SOURCE_DATE_EPOCH"] == "0"
    assert "SOURCE_DATE_EPOCH" not in os.environ


def test_context_preserves_existing_source_date_epoch() -> None:
    os.environ["SOURCE_DATE_EPOCH"] = "42"
    try:
        with deterministic_context("agg"):
            assert os.environ["SOURCE_DATE_EPOCH"] == "0"
        assert os.environ["SOURCE_DATE_EPOCH"] == "42"
    finally:
        os.environ.pop("SOURCE_DATE_EPOCH", None)


def test_context_restores_backend() -> None:
    prev = matplotlib.get_backend()
    with deterministic_context("agg"):
        pass
    assert matplotlib.get_backend().lower() == prev.lower()
