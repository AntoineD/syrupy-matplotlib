"""Immutable plugin configuration resolved once at `pytest_configure` time."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as get_distribution_version
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    import pytest

_VALID_REPORTS = frozenset({"html", "json", "basic-html"})
_TRUE_LITERALS = frozenset({"1", "true", "yes", "on"})
_FALSE_LITERALS = frozenset({"0", "false", "no", "off"})

VARIANT_TAG_PATTERN = re.compile(r"mpl-\d+\.\d+")
"""Shape a derived variant tag must have to be usable as a directory name.

The tag is never user-supplied, so this is an assertion about the
derivation rather than input validation — but it is what keeps the tag from
ever becoming `..`, a hidden directory, or anything containing a path
separator. `_extension.py` also uses it to tell variant directories apart
from unrelated ones sitting in the variant root.
"""

VARIANT_ROOT_DIRNAME = "__snapshots_variants__"
"""Directory holding every per-environment baseline variant, as
`<variant root>/<tag>/<module_stem>/<name>.png` beside the tests.

Deliberately *not* under `__snapshots__/`: syrupy accounts for everything in
that tree, and a variant describing another environment is unused there by
definition — reported as an unused snapshot (which fails the session) and
deleted by the next `--snapshot-update`. See
`_extension.MplFigureExtension._build_variant_root`.
"""

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


def derive_variant_tag() -> str:
    """Return the baseline-variant tag naming the current environment.

    The tag is `mpl-<major>.<minor>` of the installed matplotlib, and it is
    the only tag the plugin ever uses: there is no INI option, environment
    variable or flag value that can name a different one. Pinning
    matplotlib in the environment is what selects it.

    The version comes from the distribution metadata rather than
    `matplotlib.__version__` because the tag is needed in
    `pytest_report_header`, and `_plugin.py` must not import matplotlib at
    startup.

    Patch-level differences are dropped: matplotlib does not generally
    change rendering in a patch release, and `mpl-3.10` survives a
    dependency bump that `mpl-3.10.3` would not.

    Returns:
        The tag, or an empty string when matplotlib's version metadata is
        unavailable or does not parse into the expected shape — in which
        case variant lookup is disabled entirely.
    """
    try:
        raw = get_distribution_version("matplotlib")
    except PackageNotFoundError:
        return ""
    major, _, rest = raw.partition(".")
    minor = rest.partition(".")[0]
    tag = f"mpl-{major}.{minor}"
    return tag if VARIANT_TAG_PATTERN.fullmatch(tag) else ""


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

    variant: str
    """Baseline-variant tag for this environment, or an empty string when
    matplotlib's version metadata is unavailable (variant lookup off)."""

    write_variants: bool
    """`True` when this run writes variant baselines instead of canonical
    ones, i.e. `--snapshot-update --snapshot-matplotlib-pin-variant`."""


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
            `snapshot_matplotlib_savefig_kwargs` is not a JSON object, if the
            report directory resolves to the pytest rootpath or one of its
            ancestors, or if `--snapshot-matplotlib-pin-variant` is used
            without `--snapshot-update`, under pytest-xdist, with an absolute
            `--snapshot-dirname`, or without matplotlib version metadata to
            derive a tag from.
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
    if tolerance < 0:
        # A negative RMS threshold fails every comparison, including
        # byte-identical images — better to name the mistake up front.
        msg = (
            f"Invalid snapshot_matplotlib_tolerance value {tolerance_raw!r}. "
            "Expected a non-negative number."
        )
        raise ValueError(msg)
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

    variant, write_variants = _resolve_variant(config)

    return Config(
        report=report_types,
        tolerance=tolerance,
        style=style,
        backend=backend,
        auto=auto,
        remove_text=remove_text,
        savefig_kwargs=savefig_kwargs,
        report_dir=_resolve_report_dir(config),
        variant=variant,
        write_variants=write_variants,
    )


def _resolve_variant(config: pytest.Config) -> tuple[str, bool]:
    """Resolve the variant tag and whether this run writes variant baselines.

    Args:
        config: The pytest `Config` object.

    Returns:
        The `(tag, write_variants)` pair. The tag is empty when matplotlib's
        version metadata is unavailable.

    Raises:
        ValueError: If `--snapshot-matplotlib-pin-variant` is given without
            `--snapshot-update`, under pytest-xdist, with an absolute
            `--snapshot-dirname`, or with no tag to pin to.
    """
    variant = derive_variant_tag()
    pin = bool(config.getoption("--snapshot-matplotlib-pin-variant", default=False))
    if not pin:
        return variant, False
    # `update_snapshots` is syrupy's option; `pytest_configure` has already
    # refused to run without the syrupy plugin, so it is always present here.
    if not config.option.update_snapshots:
        msg = (
            "--snapshot-matplotlib-pin-variant only applies to snapshot "
            "updates; pass it together with --snapshot-update."
        )
        raise ValueError(msg)
    # Reading variants is xdist-safe; writing them is not: redundant-variant
    # deletions and their reporting are per-worker bookkeeping that never
    # reaches the controller's summary.
    if config.getoption("numprocesses", default=None):
        msg = (
            "--snapshot-matplotlib-pin-variant does not run under "
            "pytest-xdist; rerun without -n."
        )
        raise ValueError(msg)
    # The variant root is defined as sitting beside the test files; an
    # absolute --snapshot-dirname detaches the snapshot tree from them, so no
    # run can look a variant up there. Pinning would record baselines nothing
    # ever reads.
    if Path(str(config.option.snapshot_dirname)).is_absolute():
        msg = (
            "--snapshot-matplotlib-pin-variant does not support an absolute "
            "--snapshot-dirname; variant baselines live in "
            f"{VARIANT_ROOT_DIRNAME}/ beside the test files."
        )
        raise ValueError(msg)
    if not variant:
        msg = (
            "--snapshot-matplotlib-pin-variant needs matplotlib's version "
            "metadata to name the variant directory, and it could not be "
            "read. Install matplotlib as a distribution rather than from a "
            "bare source tree."
        )
        raise ValueError(msg)
    return variant, True


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
        ValueError: If the directory resolves to the pytest rootpath or one
            of its ancestors.
    """
    raw = config.getoption(
        "--snapshot-matplotlib-report-dir", default=None
    ) or _read_ini(config, "snapshot_matplotlib_report_dir", DEFAULT_REPORT_DIR)
    rootpath = Path(config.rootpath)
    report_dir = rootpath / raw
    # The plugin clears its reports and every `*.png` under this directory at
    # session start; pointed at the rootpath or an ancestor, that would delete
    # the `__snapshots__/` baselines — and above the rootpath, files that have
    # nothing to do with the project. `..` segments and symlinks hide ancestry
    # from a string comparison, so the guard works on fully resolved paths.
    if rootpath.resolve().is_relative_to(report_dir.resolve()):
        msg = (
            f"Invalid report directory {raw!r}: it resolves to the pytest "
            "rootpath or one of its ancestors. The plugin owns this directory "
            "and clears its reports and *.png files at session start, so it "
            "must be a directory of its own."
        )
        raise ValueError(msg)
    return report_dir
