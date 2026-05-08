"""Unit tests for `_figures.save_figure_to_bytes`."""

from __future__ import annotations

import struct

import matplotlib

matplotlib.use("Agg")

from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pytest

from syrupy_matplotlib._figures import save_figure_to_bytes

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def fig() -> Iterator[plt.Figure]:
    f, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    yield f
    plt.close(f)


def test_returns_png_bytes(fig: plt.Figure) -> None:
    """PNG output starts with the 8-byte PNG signature."""
    out = save_figure_to_bytes(fig, "png", {})
    assert out[:8] == b"\x89PNG\r\n\x1a\n"


def test_software_metadata_suppressed(fig: plt.Figure) -> None:
    """No `Software` tEXt chunk should be present in the PNG."""
    out = save_figure_to_bytes(fig, "png", {})
    assert b"Software" not in _png_text_chunks(out)


def test_user_software_metadata_wins(fig: plt.Figure) -> None:
    """Explicit user metadata overrides the suppression default."""
    out = save_figure_to_bytes(fig, "png", {"metadata": {"Software": "my-tool"}})
    chunks = _png_text_chunks(out)
    assert b"Software" in chunks
    assert b"my-tool" in chunks


@pytest.mark.parametrize("dpi", [50, 100, 200])
def test_dpi_kwarg_forwarded(fig: plt.Figure, dpi: int) -> None:
    """Higher DPI yields larger byte output for the same figure."""
    out = save_figure_to_bytes(fig, "png", {"dpi": dpi})
    width, height = _png_dimensions(out)
    assert width > 0
    assert height > 0
    if dpi == 200:
        out_low = save_figure_to_bytes(fig, "png", {"dpi": 50})
        w_low, _ = _png_dimensions(out_low)
        assert width > w_low


def test_caller_kwargs_not_mutated(fig: plt.Figure) -> None:
    """Input kwargs dict must not be mutated by the call."""
    kwargs = {"metadata": {"Author": "alice"}}
    save_figure_to_bytes(fig, "png", kwargs)
    assert kwargs == {"metadata": {"Author": "alice"}}


def test_figure_not_closed(fig: plt.Figure) -> None:
    """Lifecycle stays with the caller — figure must remain usable."""
    save_figure_to_bytes(fig, "png", {})
    assert plt.fignum_exists(fig.number)


def _png_text_chunks(data: bytes) -> bytes:
    """Concatenate all PNG tEXt chunk payloads into a single byte string."""
    chunks = bytearray()
    pos = 8
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        if chunk_type == b"tEXt":
            chunks.extend(data[pos + 8 : pos + 8 + length])
        pos += 12 + length
    return bytes(chunks)


def _png_dimensions(data: bytes) -> tuple[int, int]:
    """Read width and height from the IHDR chunk."""
    width = struct.unpack(">I", data[16:20])[0]
    height = struct.unpack(">I", data[20:24])[0]
    return width, height
