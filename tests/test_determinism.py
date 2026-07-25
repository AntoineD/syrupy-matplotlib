"""Unit tests for `_determinism.py`."""

from __future__ import annotations

import os
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.testing import set_font_settings_for_testing

from syrupy_matplotlib._determinism import deterministic_context

FONT_KEYS = ("text.hinting", "font.family")
"""rcParams that `set_font_settings_for_testing` owns."""


def read_expected_font_rcparams() -> dict[str, Any]:
    """Return the rcParams `set_font_settings_for_testing` installs.

    Derived by running the helper rather than hardcoding its values: which
    rcParams it sets, and to what, is a matplotlib implementation detail that
    changes across releases (3.11 flipped ``text.hinting`` from ``none`` to
    ``default`` and dropped ``text.hinting_factor``). What this plugin
    guarantees is that the helper *runs*, not what it chooses.

    Returns:
        Mapping of `FONT_KEYS` to the values the helper installs.
    """
    with matplotlib.rc_context():
        set_font_settings_for_testing()
        return {key: matplotlib.rcParams[key] for key in FONT_KEYS}


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
    expected = read_expected_font_rcparams()
    with matplotlib.rc_context():
        matplotlib.rcParams["text.hinting"] = "force_autohint"
        matplotlib.rcParams["font.family"] = ["serif"]
        # Guard against a vacuous test: the sentinels must actually differ
        # from what the helper installs, or the assertion below proves nothing.
        assert {key: matplotlib.rcParams[key] for key in FONT_KEYS} != expected
        with deterministic_context("agg"):
            assert {key: matplotlib.rcParams[key] for key in FONT_KEYS} == expected


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
    expected = read_expected_font_rcparams()
    with (
        matplotlib.rc_context(),
        plt.style.context("default", after_reset=True),
        deterministic_context("agg"),
    ):
        assert {key: matplotlib.rcParams[key] for key in FONT_KEYS} == expected
        assert matplotlib.rcParams["svg.hashsalt"] == "matplotlib"


def test_context_reapplies_on_every_call() -> None:
    """No one-shot guard: each entry must re-apply helpers from scratch."""
    expected = read_expected_font_rcparams()
    with deterministic_context("agg"):
        pass
    with matplotlib.rc_context():
        matplotlib.rcParams["text.hinting"] = "force_autohint"
        matplotlib.rcParams["svg.hashsalt"] = None
        with deterministic_context("agg"):
            assert {key: matplotlib.rcParams[key] for key in FONT_KEYS} == expected
            assert matplotlib.rcParams["svg.hashsalt"] == "matplotlib"
