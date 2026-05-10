"""Unit tests for `_determinism.py`."""

from __future__ import annotations

import os

import matplotlib
import matplotlib.pyplot as plt

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


def test_context_applies_font_settings() -> None:
    """`set_font_settings_for_testing` must run inside the context."""
    matplotlib.rcParams["text.hinting"] = "force_autohint"
    matplotlib.rcParams["text.hinting_factor"] = 1
    matplotlib.rcParams["font.family"] = ["serif"]
    with deterministic_context("agg"):
        assert matplotlib.rcParams["text.hinting"] == "none"
        assert matplotlib.rcParams["text.hinting_factor"] == 8
        assert matplotlib.rcParams["font.family"] == ["DejaVu Sans"]


def test_context_applies_reproducibility_settings() -> None:
    """`set_reproducibility_for_testing` must run inside the context."""
    matplotlib.rcParams["svg.hashsalt"] = None
    with deterministic_context("agg"):
        assert matplotlib.rcParams["svg.hashsalt"] == "matplotlib"


def test_context_reapplies_font_settings_after_style_reset() -> None:
    """Regression: font settings must survive `plt.style.context(after_reset=True)`.

    Mirrors the fixture's nesting order — style outermost, deterministic inside —
    and asserts that the rcParam reset performed by `after_reset=True` does not
    win over the testing helpers.
    """
    with (
        plt.style.context("default", after_reset=True),
        deterministic_context("agg"),
    ):
        assert matplotlib.rcParams["text.hinting"] == "none"
        assert matplotlib.rcParams["font.family"] == ["DejaVu Sans"]
        assert matplotlib.rcParams["svg.hashsalt"] == "matplotlib"


def test_context_reapplies_on_every_call() -> None:
    """No one-shot guard: each entry must re-apply helpers from scratch."""
    with deterministic_context("agg"):
        pass
    matplotlib.rcParams["text.hinting"] = "force_autohint"
    matplotlib.rcParams["svg.hashsalt"] = None
    with deterministic_context("agg"):
        assert matplotlib.rcParams["text.hinting"] == "none"
        assert matplotlib.rcParams["svg.hashsalt"] == "matplotlib"
