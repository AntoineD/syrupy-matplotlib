"""Tests for _config.py: Config resolution from CLI and INI."""

from __future__ import annotations

import pytest

from syrupy_matplotlib._config import resolve_config


def test_defaults(pytester: pytest.Pytester) -> None:
    """Config resolves sensible defaults with no CLI flags."""
    pytester.makeini("[pytest]")
    config = pytester.parseconfigure()
    cfg = resolve_config(config)
    assert cfg.tolerance == 0.0
    assert cfg.style == "default"
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
    with pytest.raises(ValueError, match="Invalid snapshot_matplotlib_auto"):
        resolve_config(pytester.parseconfigure())


def test_report_flag_default_html(pytester: pytest.Pytester) -> None:
    config = pytester.parseconfigure("--snapshot-matplotlib-report")
    cfg = resolve_config(config)
    assert cfg.report == frozenset({"html"})


def test_report_flag_multiple(pytester: pytest.Pytester) -> None:
    config = pytester.parseconfigure("--snapshot-matplotlib-report=html,json")
    cfg = resolve_config(config)
    assert cfg.report == frozenset({"html", "json"})


def test_invalid_report_type(pytester: pytest.Pytester) -> None:
    with pytest.raises(ValueError, match="Invalid --snapshot-matplotlib-report"):
        pytester.parseconfigure("--snapshot-matplotlib-report=pdf")


def test_ini_tolerance(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nsnapshot_matplotlib_tolerance = 5.5\n")
    config = pytester.parseconfigure()
    cfg = resolve_config(config)
    assert cfg.tolerance == 5.5


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
    with pytest.raises(ValueError, match="Invalid snapshot_matplotlib_remove_text"):
        resolve_config(pytester.parseconfigure())


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
        ValueError, match="Invalid snapshot_matplotlib_savefig_kwargs JSON"
    ):
        resolve_config(pytester.parseconfigure())


def test_savefig_kwargs_ini_not_object(pytester: pytest.Pytester) -> None:
    pytester.makeini("[pytest]\nsnapshot_matplotlib_savefig_kwargs = [1, 2, 3]\n")
    with pytest.raises(ValueError, match="must be a JSON object"):
        resolve_config(pytester.parseconfigure())
