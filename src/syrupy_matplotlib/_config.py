"""Immutable plugin configuration resolved once at `pytest_configure` time."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    import pytest

_VALID_REPORTS = frozenset({"html", "json", "basic-html"})
_TRUE_LITERALS = frozenset({"1", "true", "yes", "on"})
_FALSE_LITERALS = frozenset({"0", "false", "no", "off"})

DEFAULT_TOLERANCE = "0"
"""Default `snapshot_matplotlib_tolerance`; matches `matplotlib.testing`."""

DEFAULT_STYLE = "default"
"""Default `snapshot_matplotlib_style`."""

DEFAULT_BACKEND = "agg"
"""Default `snapshot_matplotlib_backend`."""

DEFAULT_AUTO = "true"
"""Default `snapshot_matplotlib_auto`."""

DEFAULT_REMOVE_TEXT = "false"
"""Default `snapshot_matplotlib_remove_text`; matches `matplotlib.testing`."""

DEFAULT_SAVEFIG_KWARGS = "{}"
"""Default `snapshot_matplotlib_savefig_kwargs`."""

DEFAULT_REPORT_DIR = "figure-report"
"""Default `snapshot_matplotlib_report_dir`, resolved against the rootpath."""


def _read_ini(config: pytest.Config, option: str, default: str) -> str:
    """Read a string INI option, treating a blank value as unset.

    A user who writes `snapshot_matplotlib_remove_text =` means "leave it
    alone", not "parse the empty string" — so every option resolves blanks
    the same way instead of one erroring while another falls back.

    Args:
        config: The pytest `Config` object.
        option: INI option name.
        default: Value to use when the option is unset or blank.

    Returns:
        The stripped INI value, or *default* when it is empty.
    """
    return str(config.getini(option) or "").strip() or default


def _parse_styles(value: str) -> tuple[str, ...]:
    """Split a comma-separated style setting into individual style names.

    Matplotlib composes styles by applying them left to right, which is how
    its own test suite reaches `("classic", "_classic_test_patch")`. Passing
    that whole string to `plt.style.context()` instead raises an opaque
    `OSError` from every test, so the option is split here, on the same
    comma convention `--snapshot-matplotlib-report` uses.

    Args:
        value: Raw INI value, e.g. `"classic,_classic_test_patch"`.

    Returns:
        The style names in application order. Never empty — a blank value
        is resolved to the default before this runs.
    """
    return tuple(s.strip() for s in value.split(",") if s.strip())


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

    style: tuple[str, ...]
    """Default matplotlib styles applied for the lifetime of the fixture,
    in application order."""

    backend: str
    """Default matplotlib backend used for rendering."""

    auto: bool
    """Default value for the fixture's auto-assert/auto-close behavior."""

    remove_text: bool
    """Default whether to strip tick labels and titles before serializing."""

    savefig_kwargs: dict[str, Any]
    """Default extra keyword arguments forwarded to `Figure.savefig()`."""

    report_dir: Path
    """Absolute directory for comparison artifacts and generated reports.
    Owned by the plugin: its reports and `*.png` files are cleared at the
    start of every session."""


def resolve_config(config: pytest.Config) -> Config:
    """Build a `Config` from CLI options and INI values.

    `report_dir` reads the CLI flag first and falls back to the INI option.
    The rest are single-source: `report` comes only from
    `--snapshot-matplotlib-report`, every other field only from its
    `snapshot_matplotlib_*` INI option, each falling back to its built-in
    default. Per-assertion overrides are applied later, by `SnapshotParams`.

    Args:
        config: The pytest `Config` object supplied to `pytest_configure`.

    Returns:
        A fully resolved, immutable `Config` instance.

    Raises:
        ValueError: If `--snapshot-matplotlib-report` contains an unrecognised
            value, if `snapshot_matplotlib_tolerance` is not a number, if
            `snapshot_matplotlib_savefig_kwargs` is not a JSON object, or if
            the report directory resolves to the pytest rootpath.
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

    tolerance_raw = _read_ini(
        config, "snapshot_matplotlib_tolerance", DEFAULT_TOLERANCE
    )
    try:
        tolerance = float(tolerance_raw)
    except ValueError as e:
        msg = (
            f"Invalid snapshot_matplotlib_tolerance value {tolerance_raw!r}. "
            "Expected a number."
        )
        raise ValueError(msg) from e
    style = _parse_styles(_read_ini(config, "snapshot_matplotlib_style", DEFAULT_STYLE))
    backend = _read_ini(config, "snapshot_matplotlib_backend", DEFAULT_BACKEND)

    auto = _parse_bool(
        _read_ini(config, "snapshot_matplotlib_auto", DEFAULT_AUTO),
        "snapshot_matplotlib_auto",
    )

    remove_text = _parse_bool(
        _read_ini(config, "snapshot_matplotlib_remove_text", DEFAULT_REMOVE_TEXT),
        "snapshot_matplotlib_remove_text",
    )

    savefig_raw = _read_ini(
        config, "snapshot_matplotlib_savefig_kwargs", DEFAULT_SAVEFIG_KWARGS
    )
    try:
        savefig_kwargs = json.loads(savefig_raw)
    except json.JSONDecodeError as e:
        msg = f"Invalid snapshot_matplotlib_savefig_kwargs JSON: {e}"
        raise ValueError(msg) from e
    if not isinstance(savefig_kwargs, dict):
        msg = "snapshot_matplotlib_savefig_kwargs must be a JSON object."
        raise ValueError(msg)  # ruff: ignore[type-check-without-type-error]

    return Config(
        report=report_types,
        tolerance=tolerance,
        style=style,
        backend=backend,
        auto=auto,
        remove_text=remove_text,
        savefig_kwargs=savefig_kwargs,
        report_dir=_resolve_report_dir(config),
    )


def _resolve_report_dir(config: pytest.Config) -> Path:
    """Resolve the artifact directory from the CLI flag, then the INI option.

    A relative value is anchored at the pytest rootpath; an absolute one is
    taken as-is. The flag exists because the racing case is two *invocations*
    sharing one config file — `tox -p`, two CI jobs on one checkout — which
    otherwise write the same artifact paths for the same test.

    Args:
        config: The pytest `Config` object.

    Returns:
        The absolute artifact directory.

    Raises:
        ValueError: If the directory resolves to the pytest rootpath itself.
    """
    raw = config.getoption(
        "--snapshot-matplotlib-report-dir", default=None
    ) or _read_ini(config, "snapshot_matplotlib_report_dir", DEFAULT_REPORT_DIR)
    rootpath = Path(config.rootpath)
    report_dir = rootpath / raw
    if report_dir == rootpath:
        # The plugin clears its own reports and every `*.png` under this
        # directory at session start; pointed at the rootpath that would
        # walk the whole project.
        msg = (
            f"Invalid report directory {raw!r}: it resolves to the pytest "
            "rootpath. The plugin owns this directory and clears its reports "
            "and *.png files at session start, so it must be a subdirectory."
        )
        raise ValueError(msg)
    return report_dir
