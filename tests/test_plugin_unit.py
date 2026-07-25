"""Unit tests for pure helpers in `_plugin.py` (no pytester)."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from syrupy_matplotlib._extension import MplFigureExtension
from syrupy_matplotlib._plugin import _format_category_line
from syrupy_matplotlib._plugin import _remove_empty_subtree
from syrupy_matplotlib._plugin import _sweep_stale_fragments
from syrupy_matplotlib._plugin import pytest_unconfigure
from syrupy_matplotlib._reporting import ResultCollector

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


def test_plugin_entry_point_import_stays_light() -> None:
    """Importing the entry-point module must not load matplotlib or syrupy.

    The module is imported at every pytest startup in every env that has
    the plugin installed; the heavy dependencies (~400 ms) must only load
    when a test actually uses the fixture.
    """
    code = (
        "import sys\n"
        "import syrupy_matplotlib._plugin\n"
        "heavy = [m for m in ('matplotlib', 'syrupy', 'jinja2') if m in sys.modules]\n"
        "assert not heavy, f'heavy imports at startup: {heavy}'\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr


def test_pytest_unconfigure_resets_extension_bindings(tmp_path: Path) -> None:
    """Session-wide class bindings are cleared so they can't leak across runs.

    The outer test session has live bindings on the class (this plugin is
    active in the running suite), so they are saved and restored around the
    check.
    """
    saved = (
        MplFigureExtension._mpl_collector,
        MplFigureExtension._mpl_rootpath,
        MplFigureExtension._mpl_update_snapshots,
        MplFigureExtension._mpl_keep_match_artifacts,
    )
    try:
        MplFigureExtension._mpl_collector = ResultCollector()
        MplFigureExtension._mpl_rootpath = tmp_path
        MplFigureExtension._mpl_update_snapshots = True
        MplFigureExtension._mpl_keep_match_artifacts = True

        pytest_unconfigure(config=None)  # type: ignore[arg-type]

        assert MplFigureExtension._mpl_collector is None
        assert MplFigureExtension._mpl_rootpath is None
        assert MplFigureExtension._mpl_update_snapshots is False
        assert MplFigureExtension._mpl_keep_match_artifacts is False
    finally:
        (
            MplFigureExtension._mpl_collector,
            MplFigureExtension._mpl_rootpath,
            MplFigureExtension._mpl_update_snapshots,
            MplFigureExtension._mpl_keep_match_artifacts,
        ) = saved


def test_sweep_stale_fragments_removes_orphans_only(tmp_path: Path) -> None:
    """Leftover fragment files go; everything else in the directory stays."""
    (tmp_path / "_results-deadbeef-gw0.json").write_text("{}")
    (tmp_path / "_results-deadbeef-gw1.json").write_text("{}")
    keeper = tmp_path / "report.html"
    keeper.write_text("kept")

    _sweep_stale_fragments(tmp_path)

    assert not list(tmp_path.glob("_results-*.json"))
    assert keeper.exists()


def test_sweep_stale_fragments_missing_dir_is_noop(tmp_path: Path) -> None:
    _sweep_stale_fragments(tmp_path / "absent")


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
