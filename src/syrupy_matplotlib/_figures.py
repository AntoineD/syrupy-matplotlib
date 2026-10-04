"""Figure serialization.

`save_figure_to_bytes()` is the single point of figure serialization: it
produces deterministic PNG bytes suitable for pixel comparison.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from matplotlib.figure import Figure


def save_figure_to_bytes(
    fig: Figure,
    ext: str,
    user_savefig_kwargs: dict[str, Any],
) -> bytes:
    """Save a matplotlib figure to an in-memory buffer and return the raw bytes.

    The PNG ``Software`` metadata field — which embeds the matplotlib
    version into every file — is suppressed so baselines stay stable across
    matplotlib upgrades. Explicit user metadata always wins.

    The figure is **not** closed here; lifecycle is owned by the caller.

    Args:
        fig: The matplotlib `Figure` to serialize.
        ext: Image format extension (e.g. `"png"`).
        user_savefig_kwargs: Extra keyword arguments forwarded to
            `Figure.savefig()`.

    Returns:
        Raw image bytes in the requested format.

    Raises:
        ValueError: If *user_savefig_kwargs* sets `format`, which the
            extension owns.
    """
    if "format" in user_savefig_kwargs:
        # Left to collide, this surfaces as `savefig() got multiple values for
        # keyword argument 'format'`, which points at matplotlib rather than at
        # the setting the user actually got wrong.
        msg = (
            f"savefig_kwargs must not set 'format': the snapshot format is fixed "
            f"to {ext!r} by the extension. Remove it from the "
            f"snapshot_matplotlib_savefig_kwargs INI option or the per-call "
            f"snapshot_matplotlib(savefig_kwargs=...) override."
        )
        raise ValueError(msg)

    kwargs = dict(user_savefig_kwargs)
    metadata = dict(kwargs.get("metadata") or {})
    metadata.setdefault("Software", None)
    kwargs["metadata"] = metadata

    buf = io.BytesIO()
    fig.savefig(buf, format=ext, **kwargs)
    return buf.getvalue()
