"""Tests for _config.py: Config resolution from CLI and INI."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syrupy_matplotlib._config import resolve_config

if TYPE_CHECKING:
    from pathlib import Path


def test_defaults(pytester: pytest.Pytester) -> None:
    """Config resolves sensible defaults with no CLI flags."""
    pytester.makeini("[pytest]")
    config = pytester.parseconfigure()
    cfg = resolve_config(config)
    assert cfg.tolerance == 0.0
    assert cfg.style == ("default",)
    assert cfg.backend == "agg"
    assert cfg.report == frozenset()
    assert cfg.auto is True
    assert cfg.remove_text is False
    assert cfg.savefig_kwargs == {}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("yes", True),
        ("true", True),
        ("1", True),
        ("no", False),
        ("false", False),
        ("0", False),
    ],
)
def test_auto_ini_values(pytester: pytest.Pytester, value: str, expected: bool) -> None:
    pytester.makeini(f"[pytest]\nsnapshot_matplotlib_auto = {value}\n")
    cfg = resolve_config(pytester.parseconfigure())
    assert cfg.auto is expected


def test_auto_ini_invalid_value(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nsnapshot_matplotlib_auto = maybe\n")
    with pytest.raises(pytest.UsageError, match="Invalid snapshot_matplotlib_auto"):
        pytester.parseconfigure()


def test_report_flag_default_html(pytester: pytest.Pytester) -> None:
    config = pytester.parseconfigure("--snapshot-matplotlib-report")
    cfg = resolve_config(config)
    assert cfg.report == frozenset({"html"})


def test_report_flag_multiple(pytester: pytest.Pytester) -> None:
    config = pytester.parseconfigure("--snapshot-matplotlib-report=html,json")
    cfg = resolve_config(config)
    assert cfg.report == frozenset({"html", "json"})


def test_invalid_report_type(pytester: pytest.Pytester) -> None:
    """`pytest_configure` translates the `ValueError` into a `UsageError`."""
    with pytest.raises(pytest.UsageError, match="Invalid --snapshot-matplotlib-report"):
        pytester.parseconfigure("--snapshot-matplotlib-report=pdf")


def test_invalid_report_type_reports_cleanly(pytester: pytest.Pytester) -> None:
    """A malformed flag prints a usage error, not an INTERNALERROR traceback."""
    pytester.makepyfile(test_noop="def test_noop(): pass")
    result = pytester.runpytest("--snapshot-matplotlib-report=pdf")

    assert result.ret != 0
    result.stderr.fnmatch_lines(["*Invalid --snapshot-matplotlib-report type(s)*"])
    assert not any(
        "INTERNALERROR" in line
        for line in result.outlines + result.errlines  # ty: ignore[unresolved-attribute]
    )


def test_disabled_syrupy_is_a_usage_error(pytester: pytest.Pytester) -> None:
    """`-p no:syrupy` yields a clean usage error, not an INTERNALERROR.

    `pytest_configure` and the fixture read syrupy's options and session;
    without the gate those lookups die as AttributeError tracebacks.
    """
    pytester.makepyfile(test_noop="def test_noop(): pass")
    result = pytester.runpytest("-p", "no:syrupy")

    assert result.ret != 0
    result.stderr.fnmatch_lines(["*requires the syrupy pytest plugin*"])
    assert not any(
        "INTERNALERROR" in line
        for line in result.outlines + result.errlines  # ty: ignore[unresolved-attribute]
    )


def test_ini_tolerance(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nsnapshot_matplotlib_tolerance = 5.5\n")
    config = pytester.parseconfigure()
    cfg = resolve_config(config)
    assert cfg.tolerance == 5.5


def test_ini_tolerance_invalid(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nsnapshot_matplotlib_tolerance = loose\n")
    with pytest.raises(
        pytest.UsageError, match="Invalid snapshot_matplotlib_tolerance"
    ):
        pytester.parseconfigure()


def test_ini_tolerance_rejects_negative(pytester: pytest.Pytester) -> None:
    """A negative RMS threshold fails every comparison; name the mistake early."""
    pytester.makeini("[pytest]\nsnapshot_matplotlib_tolerance = -1\n")
    with pytest.raises(pytest.UsageError, match="non-negative"):
        pytester.parseconfigure()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("yes", True),
        ("1", True),
        ("false", False),
        ("no", False),
        ("0", False),
    ],
)
def test_remove_text_ini_values(
    pytester: pytest.Pytester, value: str, expected: bool
) -> None:
    pytester.makeini(f"[pytest]\nsnapshot_matplotlib_remove_text = {value}\n")
    cfg = resolve_config(pytester.parseconfigure())
    assert cfg.remove_text is expected


def test_remove_text_ini_invalid(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nsnapshot_matplotlib_remove_text = sometimes\n")
    with pytest.raises(
        pytest.UsageError, match="Invalid snapshot_matplotlib_remove_text"
    ):
        pytester.parseconfigure()


def test_savefig_kwargs_ini(pytester: pytest.Pytester) -> None:
    pytester.makeini(
        "[pytest]\n"
        'snapshot_matplotlib_savefig_kwargs = {"dpi": 150, "bbox_inches": "tight"}\n'
    )
    cfg = resolve_config(pytester.parseconfigure())
    assert cfg.savefig_kwargs == {"dpi": 150, "bbox_inches": "tight"}


def test_savefig_kwargs_ini_invalid_json(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nsnapshot_matplotlib_savefig_kwargs = {not json}\n")
    with pytest.raises(
        pytest.UsageError, match="Invalid snapshot_matplotlib_savefig_kwargs JSON"
    ):
        pytester.parseconfigure()


def test_savefig_kwargs_ini_not_object(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nsnapshot_matplotlib_savefig_kwargs = [1, 2, 3]\n")
    with pytest.raises(pytest.UsageError, match="must be a JSON object"):
        pytester.parseconfigure()


def test_auto_whitespace_only_uses_default(pytester: pytest.Pytester) -> None:
    """An all-whitespace value is unset, not a malformed boolean.

    Written against `pyproject.toml` deliberately: configparser strips `.ini`
    values, so only a TOML source can deliver whitespace to `getini()`.
    """
    pytester.makepyprojecttoml(
        '[tool.pytest.ini_options]\nsnapshot_matplotlib_auto = "   "\n'
    )
    cfg = resolve_config(pytester.parseconfigure())
    assert cfg.auto is True


@pytest.mark.parametrize(
    "option",
    [
        "snapshot_matplotlib_tolerance",
        "snapshot_matplotlib_style",
        "snapshot_matplotlib_backend",
        "snapshot_matplotlib_auto",
        "snapshot_matplotlib_remove_text",
        "snapshot_matplotlib_savefig_kwargs",
    ],
)
def test_blank_ini_value_uses_default(pytester: pytest.Pytester, option: str) -> None:
    """A blank value means "unset" for every option, not just some of them.

    `snapshot_matplotlib_remove_text =` used to abort the run with
    "Expected true/false" while the same blank under
    `snapshot_matplotlib_auto` fell back to the default.
    """
    pytester.makeini(f"[pytest]\n{option} =\n")
    cfg = resolve_config(pytester.parseconfigure())
    assert cfg.tolerance == 0.0
    assert cfg.style == ("default",)
    assert cfg.backend == "agg"
    assert cfg.auto is True
    assert cfg.remove_text is False
    assert cfg.savefig_kwargs == {}


def test_style_accepts_a_composed_list(pytester: pytest.Pytester) -> None:
    """A comma-separated value composes styles the way matplotlib does.

    `plt.style.context()` applies styles left to right — that is how
    matplotlib's own suite reaches `("classic", "_classic_test_patch")`.
    Passing the whole string through raised an opaque `OSError` out of
    every test instead.
    """
    pytester.makeini(
        "[pytest]\nsnapshot_matplotlib_style = classic, _classic_test_patch\n"
    )
    cfg = resolve_config(pytester.parseconfigure())
    assert cfg.style == ("classic", "_classic_test_patch")


def test_report_dir_defaults_under_rootpath(pytester: pytest.Pytester) -> None:
    cfg = resolve_config(pytester.parseconfigure())
    assert cfg.report_dir == pytester.path / "figure-report"


def test_report_dir_ini_is_relative_to_rootpath(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nsnapshot_matplotlib_report_dir = build/figures\n")
    cfg = resolve_config(pytester.parseconfigure())
    assert cfg.report_dir == pytester.path / "build" / "figures"


def test_report_dir_cli_overrides_ini(pytester: pytest.Pytester) -> None:
    """The racing case is two invocations sharing one config file."""
    pytester.makeini("[pytest]\nsnapshot_matplotlib_report_dir = from-ini\n")
    cfg = resolve_config(
        pytester.parseconfigure("--snapshot-matplotlib-report-dir=from-cli")
    )
    assert cfg.report_dir == pytester.path / "from-cli"


def test_report_dir_accepts_an_absolute_path(
    pytester: pytest.Pytester, tmp_path: Path
) -> None:
    target = tmp_path / "elsewhere"
    cfg = resolve_config(
        pytester.parseconfigure(f"--snapshot-matplotlib-report-dir={target}")
    )
    assert cfg.report_dir == target


def test_report_dir_rejects_the_rootpath(pytester: pytest.Pytester) -> None:
    """The plugin clears `*.png` under this directory; the rootpath is off limits."""
    with pytest.raises(pytest.UsageError, match="resolves to the pytest rootpath"):
        pytester.parseconfigure("--snapshot-matplotlib-report-dir=.")


@pytest.mark.parametrize("raw", ["..", "../..", "figure-report/../.."])
def test_report_dir_rejects_relative_ancestors(
    pytester: pytest.Pytester, raw: str
) -> None:
    """`..` segments must not sneak the clearing sweep above the rootpath.

    The old guard compared the unresolved path against the rootpath alone, so
    `--snapshot-matplotlib-report-dir=..` passed — and the session-start sweep
    then deleted every `*.png` under the rootpath's parent, including the
    project's own `__snapshots__/` baselines.
    """
    with pytest.raises(pytest.UsageError, match="rootpath or one of its ancestors"):
        pytester.parseconfigure(f"--snapshot-matplotlib-report-dir={raw}")


def test_report_dir_rejects_an_absolute_ancestor(pytester: pytest.Pytester) -> None:
    """An absolute path above the rootpath is rejected like a relative one."""
    with pytest.raises(pytest.UsageError, match="rootpath or one of its ancestors"):
        pytester.parseconfigure(
            f"--snapshot-matplotlib-report-dir={pytester.path.parent}"
        )


def test_report_dir_accepts_a_sibling_directory(pytester: pytest.Pytester) -> None:
    """A `..` path that lands *beside* the rootpath, not above it, is fine."""
    cfg = resolve_config(
        pytester.parseconfigure("--snapshot-matplotlib-report-dir=../run-figures")
    )
    assert cfg.report_dir == pytester.path / ".." / "run-figures"
