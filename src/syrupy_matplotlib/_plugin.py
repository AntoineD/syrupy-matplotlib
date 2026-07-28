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
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import pytest

from . import _config
from . import _xdist
from ._config import resolve_config
from ._reporting import ResultCollector
from ._types import ImageMatchStatus

if TYPE_CHECKING:
    import weakref
    from collections.abc import Generator

    from matplotlib.figure import Figure

    from ._assertion import MplSnapshotAssertion
    from ._config import Config
    from ._reporting import ResultRecord

__all__ = ["snapshot_matplotlib"]

# This module is imported at every pytest startup via the plugin entry
# point, so it must stay cheap: matplotlib and syrupy (~400 ms together)
# are only reachable through `_fixture`/`_extension`, which are imported
# lazily, inside the code paths that actually need them.

#: Stashed on `item.stash` so `pytest_runtest_call` can run auto-assertions
#: during the call phase. Populated only when the fixture is requested.
AUTO_STATE_KEY: pytest.StashKey[
    tuple[MplSnapshotAssertion, weakref.WeakSet[Figure]]
] = pytest.StashKey()

#: Age past which an unmerged xdist result fragment is considered orphaned.
#: Generous on purpose — sweeping a live session's fragment loses its results
#: silently, while keeping a dead one an hour longer costs a few kilobytes.
_STALE_FRAGMENT_AGE_S = 3600.0

#: Top-level files the report generators write. Cleared at session start so a
#: fixed suite's green run cannot leave the previous run's report standing.
_REPORT_FILENAMES = ("report.html", "report-basic.html", "results.json", "styles.css")


@pytest.fixture
def snapshot_matplotlib(
    request: pytest.FixtureRequest,
) -> Generator[MplSnapshotAssertion, None, None]:
    """Provide a matplotlib-aware snapshot assertion.

    Thin wrapper so this entry-point module stays cheap to import: the
    matplotlib/syrupy machinery in `_fixture` loads on the first test that
    actually requests the fixture. See `_fixture.generate_snapshot_assertion`
    for the full behavior documentation.

    Args:
        request: Pytest's fixture request object.

    Yields:
        A configured `MplSnapshotAssertion` usable with `==`.
    """
    from ._fixture import generate_snapshot_assertion

    yield from generate_snapshot_assertion(request)


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
            "html (default), json, basic-html. Write "
            "--snapshot-matplotlib-report=TYPES when a test path follows, "
            "or the path is read as TYPES."
        ),
    )
    group.addoption(
        "--snapshot-matplotlib-report-dir",
        metavar="DIR",
        default=None,
        help=(
            "Directory for comparison artifacts and reports "
            f"(default: {_config.DEFAULT_REPORT_DIR}, relative to the rootdir). "
            "Overrides snapshot_matplotlib_report_dir."
        ),
    )
    group.addoption(
        "--snapshot-matplotlib-pin-variant",
        action="store_true",
        default=False,
        help=(
            "With --snapshot-update, write the baselines this run renders as "
            "variants pinned to the installed matplotlib "
            "(__snapshots__/<module>/mpl-<major>.<minor>/) instead of "
            "rewriting the canonical baselines. Comparison runs pick those up "
            "automatically and need no flag."
        ),
    )
    parser.addini(
        "snapshot_matplotlib_report_dir",
        help="Default directory for comparison artifacts and reports.",
        default=_config.DEFAULT_REPORT_DIR,
    )
    parser.addini(
        "snapshot_matplotlib_tolerance",
        help="Default RMS tolerance.",
        default=_config.DEFAULT_TOLERANCE,
    )
    parser.addini(
        "snapshot_matplotlib_style",
        help="Default matplotlib style.",
        default=_config.DEFAULT_STYLE,
    )
    parser.addini(
        "snapshot_matplotlib_backend",
        help="Default matplotlib backend.",
        default=_config.DEFAULT_BACKEND,
    )
    parser.addini(
        "snapshot_matplotlib_auto",
        help="Default auto-discover / auto-assert / auto-close behavior (true/false).",
        default=_config.DEFAULT_AUTO,
    )
    parser.addini(
        "snapshot_matplotlib_remove_text",
        help="Default remove-text behavior (true/false).",
        default=_config.DEFAULT_REMOVE_TEXT,
    )
    parser.addini(
        "snapshot_matplotlib_savefig_kwargs",
        help="Default Figure.savefig() kwargs as a JSON object, e.g. '{\"dpi\": 150}'.",
        default=_config.DEFAULT_SAVEFIG_KWARGS,
    )


# ── Plugin registration ─────────────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    """Create the `Plugin` singleton and hook up xdist when present.

    Args:
        config: The pytest `Config` object.

    Raises:
        pytest.UsageError: If the syrupy plugin is not registered, or if any
            `--snapshot-matplotlib-*` flag or `snapshot_matplotlib_*` INI
            value is malformed.
    """
    # Everything downstream reads syrupy's options (`update_snapshots`,
    # `ignore_file_extensions`) and its session object; without the plugin
    # those lookups surface as AttributeError INTERNALERROR tracebacks.
    if not config.pluginmanager.hasplugin("syrupy"):
        msg = (
            "syrupy-matplotlib requires the syrupy pytest plugin, "
            "which is not registered (disabled via -p no:syrupy?)."
        )
        raise pytest.UsageError(msg)

    # A bare `ValueError` escaping `pytest_configure` renders as a pluggy
    # INTERNALERROR traceback; `UsageError` gets pytest's one-line treatment,
    # which is what a typo'd flag deserves.
    try:
        mpl_config = resolve_config(config)
    except ValueError as e:
        raise pytest.UsageError(str(e)) from e
    diff_dir = mpl_config.report_dir

    # The session UID has to exist before xdist calls `pytest_configure_node`,
    # which it does from `DSession.pytest_sessionstart`. Generating it in our
    # own `pytest_sessionstart` happens to work only while xdist keeps that
    # hookimpl `trylast`; were it ever `tryfirst`, workers would fall back to
    # the `"main"` UID while the controller merged on the real one, and every
    # worker's results would vanish from the summary and the reports without
    # a word. `pytest_configure` runs on both sides — with `workerinput`
    # already attached on a worker — before any of that, so no hook order
    # can break it.
    is_xdist = config.pluginmanager.hasplugin("xdist")
    if is_xdist:
        _xdist.setup_session(config)

    plugin = Plugin(
        config=mpl_config,
        diff_dir=diff_dir,
        rootpath=Path(config.rootpath),
        update_snapshots=bool(config.option.update_snapshots),
        is_xdist_worker=is_xdist and _xdist._is_worker(config),
    )
    config.pluginmanager.register(plugin, name="syrupy_matplotlib_plugin")

    _warn_if_png_ignored(config)

    if is_xdist:
        config.pluginmanager.register(
            _xdist.XdistCoordinator(), name="syrupy_matplotlib_xdist"
        )


def pytest_unconfigure(config: pytest.Config) -> None:
    """Reset the class-level extension bindings made during the session.

    Without this, a later pytest session in the same process (repeated
    `pytest.main()` calls, pytester's in-process runner) reads the previous
    session's collector and rootpath.

    The extension module is looked up in `sys.modules` rather than imported:
    a session that never used the fixture never loaded matplotlib, and
    unconfigure must not become the thing that loads it.

    Args:
        config: The pytest `Config` object (unused).
    """
    ext_module = sys.modules.get(f"{__package__}._extension")
    if ext_module is None:
        return
    ext_module.MplFigureExtension._mpl_collector = None
    ext_module.MplFigureExtension._mpl_rootpath = None
    ext_module.MplFigureExtension._mpl_update_snapshots = False
    ext_module.MplFigureExtension._mpl_keep_match_artifacts = False
    ext_module.MplFigureExtension._mpl_variant = ""
    ext_module.MplFigureExtension._mpl_write_variants = False
    ext_module.MplFigureExtension._mpl_scanned_dirs.clear()


def _print_comparison_summary(
    terminalreporter: Any,
    records: list[ResultRecord],
    *,
    verbose: bool,
    deleted_variants: list[str] | None = None,
) -> None:
    """Write the image counts block to the pytest terminal.

    Only records that actually ran an image comparison contribute (update
    mode emits ``GENERATED`` records that count as "created").

    Args:
        terminalreporter: Pytest's terminal reporter.
        records: All comparison records collected this session.
        verbose: When ``True``, list the node ids under each bucket.
        deleted_variants: Snapshots whose variant baseline was removed as
            redundant, or ``None`` when none were.
    """
    deleted = deleted_variants or []
    ok_images: list[str] = []
    created_images: list[str] = []
    failed_images: list[str] = []

    for r in records:
        # `image_status` is the enum's str value; str-enum equality lets the
        # member patterns match it directly. `_` covers DIFF and MISSING.
        match r.image_status:
            case ImageMatchStatus.MATCH:
                ok_images.append(r.test_name)
            case ImageMatchStatus.GENERATED:
                created_images.append(r.test_name)
            case _:
                failed_images.append(r.test_name)

    if not (ok_images or created_images or failed_images or deleted):
        return

    terminalreporter.write_sep("=", "snapshot-matplotlib")
    line = _format_category_line("Images", ok_images, created_images, failed_images)
    if deleted:
        noun = "variant" if len(deleted) == 1 else "variants"
        line += f", {len(deleted)} {noun} deleted"
    variants_used = sorted({r.baseline_variant for r in records if r.baseline_variant})
    if variants_used:
        # Only when a variant baseline was really compared against: a suite
        # without variant directories must read exactly as it did before.
        line += f" (variant baselines: {', '.join(variants_used)})"
    terminalreporter.write_line(line)

    if verbose:
        _write_bucket(terminalreporter, "OK images", ok_images)
        _write_bucket(terminalreporter, "Created images", created_images)
        _write_bucket(terminalreporter, "Failed images", failed_images)
        _write_bucket(terminalreporter, "Deleted variant images", deleted)


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

    Routed through `issue_config_time_warning`: a bare `warnings.warn`
    during `pytest_configure` runs before pytest's warning capture is
    installed, so it bypassed the warnings summary and only surfaced on
    stderr when the user's filters happened to allow it.

    Args:
        config: The pytest `Config` object.
    """
    exts = config.option.ignore_file_extensions or []
    if any(e.strip().lstrip(".").lower() == "png" for e in exts):
        # ASCII only: the message travels through the terminal writer, whose
        # encoding on Windows is cp1252 — an em-dash arrives as byte 0x97 and
        # breaks any UTF-8 consumer of the output (pytester, CI log viewers).
        config.issue_config_time_warning(
            UserWarning(
                "--snapshot-ignore-file-extensions includes 'png'; "
                "syrupy-matplotlib will not detect unused baselines."
            ),
            stacklevel=2,
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

    rootpath: Path
    """Pytest rootpath; namespaces artifact paths under `figure-report/`."""

    update_snapshots: bool
    """`True` when `--snapshot-update` is active."""

    collector: ResultCollector
    """Accumulates comparison outcomes across the session."""

    _is_xdist_worker: bool
    """`True` when running as an xdist worker."""

    def __init__(
        self,
        config: Config,
        diff_dir: Path,
        rootpath: Path,
        update_snapshots: bool,
        is_xdist_worker: bool = False,
    ) -> None:
        """Args:
        config: Resolved plugin configuration.
        diff_dir: Directory where pixel-comparison artifacts are written.
        rootpath: Pytest rootpath, used to namespace artifact paths.
        update_snapshots: Value of `--snapshot-update`.
        is_xdist_worker: `True` when this process is an xdist worker.
        """  # ruff: ignore[missing-blank-line-after-summary]
        self.config = config
        self.diff_dir = diff_dir
        self.rootpath = rootpath
        self.update_snapshots = update_snapshots
        self.collector = ResultCollector(results_root=diff_dir)
        self._is_xdist_worker = is_xdist_worker

    def bind_extension_class(self) -> None:
        """Stamp session-wide state onto `MplFigureExtension` class attributes.

        Called from fixture setup rather than `pytest_configure` so the
        entry-point module never imports the matplotlib-heavy extension at
        startup. Idempotent — every fixture instance re-stamps the same
        session values.
        """
        from ._extension import MplFigureExtension

        MplFigureExtension._mpl_collector = self.collector
        MplFigureExtension._mpl_rootpath = self.rootpath
        MplFigureExtension._mpl_update_snapshots = self.update_snapshots
        MplFigureExtension._mpl_keep_match_artifacts = bool(self.config.report)
        MplFigureExtension._mpl_variant = self.config.variant
        MplFigureExtension._mpl_write_variants = self.config.write_variants

    def pytest_report_header(self) -> str | None:
        """Announce that this run pins baselines to its environment.

        Only variant-writing runs get a header line. A comparison run cannot
        know whether any variant exists until tests execute, and printing the
        tag unconditionally would put a line in front of every suite that has
        the plugin installed and never renders a figure. Comparison runs that
        do read a variant say so in the terminal summary instead.

        Returns:
            The header line, or `None` when this run writes canonical
            baselines.
        """
        if not self.config.write_variants:
            return None
        # ASCII only: this line goes through the terminal writer, whose
        # encoding on Windows is cp1252.
        return (
            f"snapshot-matplotlib: environment '{self.config.variant}' "
            "-> pinning variant baselines"
        )

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

        Returns:
            The result produced by the wrapped `pytest_runtest_call` hook.

        Yields:
            Control to the inner hookimpls so the test body runs first.
        """
        result = yield
        # Guard on the stash key before importing: this wrapper runs for
        # every test, and `_fixture` must only load when the fixture was
        # actually requested somewhere.
        if AUTO_STATE_KEY in item.stash:
            from ._fixture import run_auto_assertions

            run_auto_assertions(item)
        return result

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        """Clear what an earlier session left in the artifact directory.

        Controller-only: a worker shares the directory with its siblings and
        would delete artifacts they are still writing. Skipped under
        ``--collect-only``, which runs no comparison and writes nothing — a
        quick collection pass must not destroy the failure report the user
        may be reading.

        Args:
            session: The current pytest session.
        """
        if self._is_xdist_worker or session.config.option.collectonly:
            return
        _sweep_stale_fragments(self.diff_dir)
        _clear_previous_artifacts(self.diff_dir)

    def pytest_sessionfinish(
        self,
        session: pytest.Session,
        exitstatus: int,
    ) -> None:
        """Merge xdist result fragments and write configured reports.

        Skipped under ``--collect-only`` — no comparisons ran, and an empty
        report (or an empty fragment) would overwrite what the previous real
        run wrote.

        Args:
            session: The current pytest session.
            exitstatus: Session exit code (unused).
        """
        if session.config.option.collectonly:
            return
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
            deleted_variants=self.collector.deleted_variants,
        )
        self._warn_about_stale_variants(terminalreporter)

    def _warn_about_stale_variants(self, terminalreporter: Any) -> None:
        """Warn that a canonical re-baseline may have outdated the variants.

        The tags come from `MplFigureExtension`, which collects them only
        while overwriting a canonical baseline with different bytes, and only
        from the directory being overwritten. So an idempotent
        `--snapshot-update` stays quiet — the warning claims a rewrite — and
        so does one that rewrote a module with no variants next to it.

        Only the environment a variant was generated in can say whether it
        still differs from the canonical baseline, so the plugin cannot
        refresh or verify them here — the other environments' runs will fail,
        which is the signal to regenerate.

        Best-effort under xdist: the directories are seen by the workers, and
        this runs on the controller.

        Args:
            terminalreporter: Pytest's terminal reporter.
        """
        tags = self.collector.variant_dirs_present
        if not tags:
            return
        # ASCII only: see the note in `_warn_if_png_ignored`.
        terminalreporter.write_line(
            "canonical baselines rewritten; variant baselines for "
            f"{', '.join(sorted(tags))} may now be stale. Regenerate them with "
            "--snapshot-update --snapshot-matplotlib-pin-variant in each of "
            "those environments."
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


def _sweep_stale_fragments(diff_dir: Path) -> None:
    """Delete xdist result fragments a crashed earlier session left behind.

    Fragments are merged and unlinked at session end; any still present at
    session start are orphans from a controller that never finished. Left
    alone they accumulate forever and keep `figure-report/` from being
    pruned as empty.

    Fragment names carry the writing session's UID, but a sweep cannot tell
    a dead session's UID from a live one's, so it goes by age instead: a
    second pytest session sharing this rootdir (`tox -p`, two shells, two
    CI jobs on one checkout) may have workers whose fragments are written
    and not yet merged, and deleting those would silently drop their
    results from the other run's report. Workers write at session end and
    the controller merges seconds later, so anything older than
    `_STALE_FRAGMENT_AGE_S` belongs to a run that is not coming back.

    Args:
        diff_dir: The `figure-report/` directory to sweep.
    """
    cutoff = time.time() - _STALE_FRAGMENT_AGE_S
    # The trailing `*` also catches `.json.tmp` files a worker killed
    # mid-write left behind (fragments are written to a temp name and
    # renamed into place).
    for stale in diff_dir.glob("_results-*.json*"):
        with contextlib.suppress(OSError):
            if stale.stat().st_mtime < cutoff:
                stale.unlink()


def _clear_previous_artifacts(diff_dir: Path) -> None:
    """Delete the reports and comparison images an earlier session wrote.

    `figure-report/` is meant to describe the run that just finished. A
    failing run writes `report.html` plus actual/baseline/diff PNGs; once
    the suite is fixed, the next run writes no report at all — and left
    alone the old one stays, still listing failures that no longer exist.
    A CI job archiving the directory out of a cached workspace then
    publishes a report contradicting the run it came from.

    Only files this plugin writes are removed: the reports by name, the
    comparison artifacts by extension. Result fragments are deliberately
    left to `_sweep_stale_fragments`, which age-gates them because
    deleting a live session's fragment loses its results for good. A
    report is a final output that its own session rewrites at session end,
    so a concurrent run loses nothing here that it will not rewrite.

    Args:
        diff_dir: The artifact directory to clear.
    """
    for name in _REPORT_FILENAMES:
        with contextlib.suppress(OSError):
            (diff_dir / name).unlink(missing_ok=True)
    # Hardcoded rather than read off `MplFigureExtension.file_extension`:
    # this module must not import the matplotlib-heavy extension.
    for image in diff_dir.rglob("*.png"):
        with contextlib.suppress(OSError):
            image.unlink()


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
