"""syrupy-matplotlib plugin: hook registration and orchestration.

The plugin owns:

- CLI/INI registration for the `--snapshot-matplotlib-*` options.
- A `Plugin` singleton exposing `config`, `collector`, and `diff_dir` to the
  `snapshot_matplotlib` fixture.
- Session-finish reporting (HTML/JSON) and xdist fragment merge for the
  collector.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import pytest

from . import _xdist
from ._config import resolve_config
from ._extension import MplFigureExtension
from ._fixture import snapshot_matplotlib as _snapshot_matplotlib_fixture
from ._reporting import ResultCollector
from ._types import ImageMatchStatus

if TYPE_CHECKING:
    from collections.abc import Generator

    from ._config import Config
    from ._reporting import ResultRecord

__all__ = ["snapshot_matplotlib"]

#: Re-exported so pytest discovers the fixture from this entry-point module.
snapshot_matplotlib = _snapshot_matplotlib_fixture


# ── CLI / INI registration ──────────────────────────────────────────────────


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register `--snapshot-matplotlib-*` CLI flags and INI options.

    Args:
        parser: The pytest argument parser.
    """
    group = parser.getgroup("syrupy-matplotlib", "Matplotlib figure comparison")
    group.addoption(
        "--snapshot-matplotlib-report",
        metavar="TYPES",
        nargs="?",
        const="html",
        default=None,
        help=(
            "Generate a report. TYPES is a comma-separated list of "
            "html (default), json, basic-html."
        ),
    )
    parser.addini(
        "snapshot_matplotlib_tolerance", help="Default RMS tolerance.", default="0"
    )
    parser.addini(
        "snapshot_matplotlib_style", help="Default matplotlib style.", default="default"
    )
    parser.addini(
        "snapshot_matplotlib_backend", help="Default matplotlib backend.", default="agg"
    )
    parser.addini(
        "snapshot_matplotlib_auto",
        help="Default auto-discover / auto-assert / auto-close behavior (true/false).",
        default="",
    )
    parser.addini(
        "snapshot_matplotlib_remove_text",
        help="Default remove-text behavior (true/false).",
        default="false",
    )
    parser.addini(
        "snapshot_matplotlib_savefig_kwargs",
        help="Default Figure.savefig() kwargs as a JSON object, e.g. '{\"dpi\": 150}'.",
        default="{}",
    )


# ── Plugin registration ─────────────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    """Create the `Plugin` singleton and hook up xdist when present.

    Args:
        config: The pytest `Config` object.
    """
    mpl_config = resolve_config(config)
    diff_dir = Path(config.rootpath) / "figure-report"

    plugin = Plugin(config=mpl_config, diff_dir=diff_dir)
    config.pluginmanager.register(plugin, name="syrupy_matplotlib_plugin")

    # Bind session-wide state on the extension class so the per-assertion
    # stamping doesn't have to thread it through.
    MplFigureExtension._mpl_collector = plugin.collector
    MplFigureExtension._mpl_rootpath = Path(config.rootpath)
    MplFigureExtension._mpl_update_snapshots = bool(config.option.update_snapshots)
    MplFigureExtension._mpl_keep_match_artifacts = bool(mpl_config.report)

    _warn_if_png_ignored(config)

    if config.pluginmanager.hasplugin("xdist"):
        config.pluginmanager.register(
            _xdist.XdistCoordinator(), name="syrupy_matplotlib_xdist"
        )


def _print_comparison_summary(
    terminalreporter: Any,
    records: list[ResultRecord],
    *,
    verbose: bool,
) -> None:
    """Write the image counts block to the pytest terminal.

    Only records that actually ran an image comparison contribute (update
    mode emits ``GENERATED`` records that count as "created").

    Args:
        terminalreporter: Pytest's terminal reporter.
        records: All comparison records collected this session.
        verbose: When ``True``, list the node ids under each bucket.
    """
    ok_images: list[str] = []
    created_images: list[str] = []
    failed_images: list[str] = []

    for r in records:
        match r.image_status:
            case ImageMatchStatus.MATCH.value:
                ok_images.append(r.test_name)
            case ImageMatchStatus.GENERATED.value:
                created_images.append(r.test_name)
            case _:
                failed_images.append(r.test_name)

    if not (ok_images or created_images or failed_images):
        return

    terminalreporter.write_sep("=", "snapshot-matplotlib")
    terminalreporter.write_line(
        _format_category_line("Images", ok_images, created_images, failed_images)
    )

    if verbose:
        _write_bucket(terminalreporter, "OK images", ok_images)
        _write_bucket(terminalreporter, "Created images", created_images)
        _write_bucket(terminalreporter, "Failed images", failed_images)


def _format_category_line(
    title: str,
    ok: list[str],
    created: list[str],
    failed: list[str],
) -> str:
    """Format one summary line.

    Pure update-mode runs collapse to ``"Title: N created"``. Otherwise the
    classic ``"N OK, M failed"`` format is preserved, with an optional
    trailing ``", K created"`` fragment when both styles appear together.

    Args:
        title: Bucket label (e.g. ``"Images"``).
        ok: Node ids that passed.
        created: Node ids whose baselines were just written.
        failed: Node ids that failed.

    Returns:
        A single formatted line.
    """
    if created and not (ok or failed):
        return f"{title}: {len(created)} created"
    line = f"{title}: {len(ok)} OK, {len(failed)} failed"
    if created:
        line += f", {len(created)} created"
    return line


def _write_bucket(terminalreporter: Any, title: str, names: list[str]) -> None:
    """Render one labelled group of test node ids.

    Args:
        terminalreporter: Pytest's terminal reporter.
        title: Heading for the bucket.
        names: Node ids to list under the heading.
    """
    if not names:
        return
    terminalreporter.write_line(f"  {title} ({len(names)}):")
    for n in names:
        terminalreporter.write_line(f"    {n}")


def _warn_if_png_ignored(config: pytest.Config) -> None:
    """Emit a warning when `--snapshot-ignore-file-extensions` includes `png`.

    Syrupy walks `__snapshots__/` for unused-snapshot detection and skips
    files whose extension is in the ignore list; ignoring `png` would
    silently disable figure discovery.

    Args:
        config: The pytest `Config` object.
    """
    import warnings

    exts = config.option.ignore_file_extensions or []
    if any(e.strip().lstrip(".").lower() == "png" for e in exts):
        warnings.warn(
            "--snapshot-ignore-file-extensions includes 'png' — "
            "syrupy-matplotlib will not detect unused baselines.",
            stacklevel=1,
        )


# ── Plugin class ────────────────────────────────────────────────────────────


class Plugin:
    """Singleton holding session-wide state the fixture reads from.

    Exposes `config`, `collector`, and `diff_dir` as public attributes so
    `_fixture.py` can assemble a `MplSnapshotAssertion` without importing
    module-level globals.
    """

    config: Config
    """Resolved plugin configuration."""

    diff_dir: Path
    """Directory where pixel-comparison artifacts and reports land."""

    collector: ResultCollector
    """Accumulates comparison outcomes across the session."""

    _is_xdist_worker: bool
    """`True` when running as an xdist worker."""

    def __init__(self, config: Config, diff_dir: Path) -> None:
        """Args:
        config: Resolved plugin configuration.
        diff_dir: Directory where pixel-comparison artifacts are written.
        """  # noqa: D205
        self.config = config
        self.diff_dir = diff_dir
        self.collector = ResultCollector(results_root=diff_dir)
        self._is_xdist_worker = False

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(self, item: pytest.Item) -> Generator[None, None, None]:
        """Run auto-assertions during the call phase, not teardown.

        A mismatch raised here is recorded as a test failure (the call phase
        propagates it), so it shows up under "FAILED" in the terminal and
        gets the standard pytest treatment. Doing this during teardown would
        produce an "ERROR at teardown" report instead, which doesn't count
        as a test failure.

        Args:
            item: The pytest item being executed.

        Yields:
            Control to the inner hookimpls so the test body runs first.
        """
        from ._fixture import run_auto_assertions

        yield
        run_auto_assertions(item)

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        """Initialise xdist state at session start.

        Args:
            session: The current pytest session.
        """
        if session.config.pluginmanager.hasplugin("xdist"):
            _xdist.setup_session(session.config)
            self._is_xdist_worker = _xdist._is_worker(session.config)

    def pytest_sessionfinish(
        self,
        session: pytest.Session,
        exitstatus: int,
    ) -> None:
        """Merge xdist result fragments and write configured reports.

        Args:
            session: The current pytest session.
            exitstatus: Session exit code (unused).
        """
        if self._is_xdist_worker:
            self._save_xdist_results(session.config)
            return

        # Outside xdist, `merge_worker_fragments` finds nothing and no-ops.
        self._merge_xdist_results(session.config)

        if self.config.report:
            self._write_reports()
        elif self._should_auto_emit_failed_report(session):
            self._write_failed_only_html_report()
        else:
            _remove_empty_subtree(self.diff_dir)

    def pytest_terminal_summary(
        self,
        terminalreporter: Any,
        exitstatus: int,
        config: pytest.Config,
    ) -> None:
        """Print an image counts summary at the end of the run.

        Runs only on the xdist controller (or in non-xdist mode). With
        ``-v`` (or higher verbosity), each bucket is expanded to list the
        pytest node ids that landed in it.

        Args:
            terminalreporter: Pytest's terminal reporter.
            exitstatus: Session exit code (unused).
            config: The pytest `Config` object.
        """
        if self._is_xdist_worker:
            return
        _print_comparison_summary(
            terminalreporter,
            self.collector.records,
            verbose=int(config.option.verbose) >= 1,
        )

    def _write_reports(self) -> None:
        """Generate all configured report formats under `self.diff_dir`."""
        from ._html_report import generate_basic_html_report
        from ._html_report import generate_html_report
        from ._json_report import generate_json_report

        if "html" in self.config.report:
            generate_html_report(self.collector, self.diff_dir)
        if "basic-html" in self.config.report:
            generate_basic_html_report(self.collector, self.diff_dir)
        if "json" in self.config.report:
            generate_json_report(self.collector, self.diff_dir)

    def _should_auto_emit_failed_report(self, session: pytest.Session) -> bool:
        """Decide whether to emit the default failed-only HTML report.

        Returns ``False`` under ``--snapshot-update`` (where ``GENERATED``
        records aren't real failures) and when the session had no failed
        comparisons.

        Args:
            session: The current pytest session.

        Returns:
            ``True`` when at least one record failed and update mode is off.
        """
        if session.config.option.update_snapshots:
            return False
        return self.collector.compute_summary().failed > 0

    def _write_failed_only_html_report(self) -> None:
        """Generate `figure-report/report.html` containing only failures."""
        from ._html_report import generate_failed_only_html_report

        generate_failed_only_html_report(self.collector, self.diff_dir)

    def _save_xdist_results(self, config: pytest.Config) -> None:
        """Serialize this worker's results to a JSON fragment file.

        Args:
            config: The worker's pytest `Config`.
        """
        path = (
            self.diff_dir
            / f"_results-{_xdist.get_uid(config)}-{_xdist.get_worker_id()}.json"
        )
        self.collector.save_worker_json(path)

    def _merge_xdist_results(self, config: pytest.Config) -> None:
        """Merge result fragments from all workers into the collector.

        Args:
            config: The controller's pytest `Config`.
        """
        merged = _xdist.merge_worker_fragments(self.diff_dir, _xdist.get_uid(config))
        self.collector.merge_serialized(merged)


def _remove_empty_subtree(root: Path) -> None:
    """Remove *root* and any empty descendants. No-op if *root* is missing.

    Walks bottom-up so a directory whose children all become empty is
    itself eligible for removal in the same pass.

    Args:
        root: Directory to prune; left untouched if it contains files.
    """
    if not root.exists():
        return
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        with contextlib.suppress(OSError):
            d.rmdir()
    with contextlib.suppress(OSError):
        root.rmdir()
