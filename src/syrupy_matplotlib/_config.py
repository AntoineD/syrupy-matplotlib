"""Immutable plugin configuration resolved once at `pytest_configure` time."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    import pytest

_VALID_REPORTS = frozenset({"html", "json", "basic-html"})
_TRUE_LITERALS = frozenset({"1", "true", "yes", "on"})
_FALSE_LITERALS = frozenset({"0", "false", "no", "off"})


def _parse_bool(value: str, option: str) -> bool:
    """Parse a case-insensitive boolean string.

    Args:
        value: Raw string from CLI or INI.
        option: Option name used in the error message.

    Returns:
        The parsed boolean.

    Raises:
        ValueError: If *value* is not a recognised literal.
    """
    v = value.strip().lower()
    if v in _TRUE_LITERALS:
        return True
    if v in _FALSE_LITERALS:
        return False
    msg = f"Invalid {option} value {value!r}. Expected true/false."
    raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Config:
    """All plugin settings resolved from CLI flags and INI options.

    Created once in `pytest_configure`; never mutated afterwards.
    """

    report: frozenset[str]
    """Set of report formats to generate at session end
    (subset of `{"html", "json", "basic-html"}`).
    """

    tolerance: float
    """Default RMS tolerance for pixel comparison."""

    style: str
    """Default matplotlib style applied for the lifetime of the fixture."""

    backend: str
    """Default matplotlib backend used for rendering."""

    auto: bool
    """Default value for the fixture's auto-assert/auto-close behavior."""

    remove_text: bool
    """Default whether to strip tick labels and titles before serializing."""

    savefig_kwargs: dict[str, Any]
    """Default extra keyword arguments forwarded to `Figure.savefig()`."""


def resolve_config(config: pytest.Config) -> Config:
    """Build a `Config` from CLI options and INI values.

    CLI flags take precedence over INI options; INI options take precedence
    over built-in defaults.

    Args:
        config: The pytest `Config` object supplied to `pytest_configure`.

    Returns:
        A fully resolved, immutable `Config` instance.

    Raises:
        ValueError: If `--snapshot-matplotlib-report` contains an unrecognised value.
    """
    report_raw: str = (
        config.getoption("--snapshot-matplotlib-report", default=None) or ""
    )
    report_types: frozenset[str] = frozenset(
        t.strip() for t in report_raw.split(",") if t.strip()
    )
    invalid = report_types - _VALID_REPORTS
    if invalid:
        msg = (
            f"Invalid --snapshot-matplotlib-report type(s): {sorted(invalid)}. "
            f"Valid: {sorted(_VALID_REPORTS)}"
        )
        raise ValueError(msg)

    tolerance = float(config.getini("snapshot_matplotlib_tolerance"))
    style = str(config.getini("snapshot_matplotlib_style"))
    backend = str(config.getini("snapshot_matplotlib_backend"))

    auto_ini: str = config.getini("snapshot_matplotlib_auto") or ""
    auto = _parse_bool(auto_ini, "snapshot_matplotlib_auto") if auto_ini else True

    remove_text = _parse_bool(
        str(config.getini("snapshot_matplotlib_remove_text")),
        "snapshot_matplotlib_remove_text",
    )

    savefig_raw = (
        str(config.getini("snapshot_matplotlib_savefig_kwargs")).strip() or "{}"
    )
    try:
        savefig_kwargs = json.loads(savefig_raw)
    except json.JSONDecodeError as e:
        msg = f"Invalid snapshot_matplotlib_savefig_kwargs JSON: {e}"
        raise ValueError(msg) from e
    if not isinstance(savefig_kwargs, dict):
        msg = "snapshot_matplotlib_savefig_kwargs must be a JSON object."
        raise ValueError(msg)  # noqa: TRY004

    return Config(
        report=report_types,
        tolerance=tolerance,
        style=style,
        backend=backend,
        auto=auto,
        remove_text=remove_text,
        savefig_kwargs=savefig_kwargs,
    )
