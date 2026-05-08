"""Deterministic matplotlib environment setup.

Reuses `matplotlib.testing` functions directly instead of reimplementing.
`SOURCE_DATE_EPOCH` is managed in a context manager to prevent the env-var
leak bug present in pytest-mpl.
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING

import matplotlib
from matplotlib.testing import set_font_settings_for_testing
from matplotlib.testing import set_reproducibility_for_testing

if TYPE_CHECKING:
    from collections.abc import Generator

_TESTING_HELPERS_APPLIED = False


@contextlib.contextmanager
def deterministic_context(backend: str) -> Generator[None, None, None]:
    """Set up a fully deterministic matplotlib environment for one test.

    Calls `matplotlib.testing` helpers which handle font settings (DejaVu
    Sans, no hinting) and SVG reproducibility (`svg.hashsalt`); they only
    fire once per process because they mutate process-global rcParams that
    no style context reverts. Also sets `SOURCE_DATE_EPOCH=0` (consumed by
    matplotlib's PDF/EPS writers and by other libraries that observe it),
    restoring the previous value — or removing the variable — in the
    `finally` block. The matplotlib backend is switched for the duration
    and restored afterwards (`matplotlib.use()` is cheap when the backend
    is already active).

    Args:
        backend: Matplotlib backend name to activate (e.g. `"agg"`).

    Yields:
        Nothing; the caller yields inside this context to run the test.
    """
    global _TESTING_HELPERS_APPLIED

    prev_backend = matplotlib.get_backend()
    prev_epoch = os.environ.get("SOURCE_DATE_EPOCH")

    try:
        matplotlib.use(backend)
        if not _TESTING_HELPERS_APPLIED:
            set_font_settings_for_testing()
            set_reproducibility_for_testing()
            _TESTING_HELPERS_APPLIED = True
        os.environ["SOURCE_DATE_EPOCH"] = "0"
        yield
    finally:
        if prev_epoch is None:
            os.environ.pop("SOURCE_DATE_EPOCH", None)
        else:
            os.environ["SOURCE_DATE_EPOCH"] = prev_epoch
        matplotlib.use(prev_backend)
