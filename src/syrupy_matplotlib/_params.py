"""Per-assertion parameters for the `snapshot_matplotlib` fixture.

`SnapshotParams` carries the effective configuration for a single
`assert fig == snapshot_matplotlib` invocation: tolerance, savefig kwargs,
remove-text, and test-scoped style/backend resolved from the plugin config.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from ._config import Config


@dataclass(frozen=True, slots=True)
class SnapshotParams:
    """Effective per-assertion parameters.

    Created by `from_config()` at fixture setup, optionally refined via
    `merge()` when the user calls `snapshot_matplotlib(tolerance=..., ...)`.
    """

    tolerance: float
    """RMS threshold for pixel comparison."""

    style: str
    """Matplotlib style applied to the fixture's `plt.style.context`."""

    backend: str
    """Matplotlib backend used for rendering."""

    remove_text: bool
    """When `True`, strip tick labels and titles before serializing."""

    savefig_kwargs: dict[str, Any] = field(default_factory=dict)
    """Extra keyword arguments forwarded to `Figure.savefig()`."""

    @classmethod
    def from_config(cls, config: Config) -> SnapshotParams:
        """Build default params from the resolved plugin configuration.

        Args:
            config: Plugin configuration resolved once at `pytest_configure`.

        Returns:
            A fully populated `SnapshotParams` instance.
        """
        return cls(
            tolerance=config.tolerance,
            style=config.style,
            backend=config.backend,
            remove_text=config.remove_text,
            savefig_kwargs=dict(config.savefig_kwargs),
        )

    def merge(
        self,
        *,
        tolerance: float | None = None,
        savefig_kwargs: dict[str, Any] | None = None,
        remove_text: bool | None = None,
    ) -> SnapshotParams:
        """Return a new instance with non-`None` overrides applied.

        `style` and `backend` cannot be overridden per-call: they must be
        active before the figure is drawn, which is before the assertion runs.

        Args:
            tolerance: RMS threshold override.
            savefig_kwargs: Extra `Figure.savefig()` kwargs override
                (replaces, does not merge).
            remove_text: Whether to strip text before saving.

        Returns:
            A new `SnapshotParams` reflecting the merged values.
        """
        kwargs: dict[str, Any] = {}
        if tolerance is not None:
            kwargs["tolerance"] = float(tolerance)
        if savefig_kwargs is not None:
            kwargs["savefig_kwargs"] = dict(savefig_kwargs)
        if remove_text is not None:
            kwargs["remove_text"] = bool(remove_text)
        return replace(self, **kwargs)
