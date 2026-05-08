"""Unit tests for pure helpers in `_plugin.py` (no pytester)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syrupy_matplotlib._plugin import _format_category_line
from syrupy_matplotlib._plugin import _remove_empty_subtree

if TYPE_CHECKING:
    from pathlib import Path


def test_format_category_line_created_only() -> None:
    line = _format_category_line("Images", ok=[], created=["a"], failed=[])
    assert line == "Images: 1 created"


def test_format_category_line_ok_and_failed() -> None:
    line = _format_category_line("Images", ok=["a"], created=[], failed=["b"])
    assert line == "Images: 1 OK, 1 failed"


def test_format_category_line_all_three_appends_created() -> None:
    """Mixed counts keep the classic line and append a ``, K created`` tail."""
    line = _format_category_line("Images", ok=["a"], created=["c"], failed=["b"])
    assert line == "Images: 1 OK, 1 failed, 1 created"


def test_remove_empty_subtree_missing_root_is_noop(tmp_path: Path) -> None:
    """Removing a non-existent directory is a no-op."""
    _remove_empty_subtree(tmp_path / "absent")


def test_remove_empty_subtree_prunes_empty_descendants(tmp_path: Path) -> None:
    """Empty subdirs are removed bottom-up along with the root."""
    root = tmp_path / "figure-report"
    (root / "tests" / "test_plots").mkdir(parents=True)
    (root / "tests" / "test_other").mkdir(parents=True)

    _remove_empty_subtree(root)

    assert not root.exists()


def test_remove_empty_subtree_keeps_non_empty_root(tmp_path: Path) -> None:
    """Directory with files stays; descendants that became empty are removed."""
    root = tmp_path / "figure-report"
    nested = root / "tests" / "test_plots"
    nested.mkdir(parents=True)
    keeper = root / "report.html"
    keeper.write_text("kept")

    _remove_empty_subtree(root)

    assert root.exists()
    assert keeper.exists()
    assert not nested.exists()
