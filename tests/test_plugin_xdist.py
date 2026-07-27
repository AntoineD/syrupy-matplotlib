"""Integration tests exercising the xdist code paths in `_plugin.py`."""

from __future__ import annotations

import json
import textwrap

import pytest

XDIST_TEST = textwrap.dedent("""\
    import matplotlib.pyplot as plt
    import pytest

    @pytest.mark.parametrize("n", [1, 2, 3, 4])
    def test_plots(snapshot_matplotlib, n):
        fig, ax = plt.subplots(); ax.plot([0, n])
        assert fig == snapshot_matplotlib
""")


@pytest.mark.parametrize("workers", [1, 2, 4])
def test_xdist_report_merge(pytester: pytest.Pytester, workers: int) -> None:
    """Workers serialise JSON fragments; controller merges + writes report."""
    pytester.makepyfile(test_plots=XDIST_TEST)
    pytester.runpytest("--snapshot-update", "-p", "no:xdist")

    result = pytester.runpytest("-n", str(workers), "--snapshot-matplotlib-report=json")
    result.assert_outcomes(passed=4)

    report_path = pytester.path / "figure-report" / "results.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text())
    assert data["summary"]["total"] == 4
    assert data["summary"]["passed"] == 4


def test_xdist_same_test_name_in_different_modules(pytester: pytest.Pytester) -> None:
    """Two modules with same-named tests don't race on `figure-report/` paths.

    Without per-test subdirectories, both modules' `test_plot[a]` would
    write to `figure-report/test_plot[a].png` and `..-expected.png`, then
    `compare_images` would read whichever bytes were last written —
    producing spurious failures (and all-black diff images) under xdist.
    """
    src = textwrap.dedent("""\
        import matplotlib.pyplot as plt
        import pytest

        @pytest.mark.parametrize("a", ["x", "y"])
        def test_plot(snapshot_matplotlib, a):
            fig, ax = plt.subplots(); ax.plot([1, 2, 3], label=a)
            assert fig == snapshot_matplotlib
    """)
    pkg = pytester.mkpydir("pkg")
    sub = pkg / "sub"
    sub.mkdir()
    (sub / "__init__.py").write_text("")
    (pkg / "test_plots.py").write_text(src)
    (sub / "test_plots.py").write_text(src)

    pytester.runpytest("--snapshot-update", "-p", "no:xdist").assert_outcomes(passed=4)

    # Run with the report flag so MATCH artifacts are kept under their
    # per-module subdirs; without it, an all-pass run leaves no files.
    result = pytester.runpytest("-n", "4", "--snapshot-matplotlib-report=json")
    result.assert_outcomes(passed=4, failed=0, errors=0)

    report = pytester.path / "figure-report"
    pkg_dir = report / "pkg" / "test_plots"
    sub_dir = report / "pkg" / "sub" / "test_plots"
    assert pkg_dir.is_dir()
    assert sub_dir.is_dir()


def test_no_xdist_plugin_report_path(pytester: pytest.Pytester) -> None:
    """With `-p no:xdist`, `pytest_sessionfinish` takes the non-xdist branch."""
    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt

            def test_one(snapshot_matplotlib):
                fig, ax = plt.subplots(); ax.plot([1, 2, 3])
                assert fig == snapshot_matplotlib
        """)
    )
    pytester.runpytest("-p", "no:xdist", "--snapshot-update").assert_outcomes(passed=1)
    pytester.runpytest(
        "-p", "no:xdist", "--snapshot-matplotlib-report=json"
    ).assert_outcomes(passed=1)

    report = pytester.path / "figure-report" / "results.json"
    assert report.exists()


def test_worker_uid_is_set_before_nodes_are_configured(
    pytester: pytest.Pytester,
) -> None:
    """The session UID must exist by the time xdist configures its workers.

    xdist calls `pytest_configure_node` from `DSession.pytest_sessionstart`.
    Deriving the UID in the plugin's own `pytest_sessionstart` only works
    while xdist keeps that hookimpl `trylast` — flip it and workers fall
    back to the `"main"` UID while the controller merges on the real one,
    so every worker's results disappear from the summary and the reports
    with no error anywhere. Resolving it in `pytest_configure` removes the
    dependency; this test pins that.
    """
    pytester.makepyfile(test_plots=XDIST_TEST)
    pytester.runpytest("--snapshot-update", "-p", "no:xdist").assert_outcomes(passed=4)

    # Written only now: `pytest_configure_node` is an xdist hook, and a
    # conftest declaring it makes the `-p no:xdist` run above fail to load.
    pytester.makeconftest("""\
        from pathlib import Path

        import pytest

        from syrupy_matplotlib import _xdist


        @pytest.hookimpl(trylast=True)
        def pytest_configure(config):
            Path(config.rootpath, "at-configure.txt").write_text(
                _xdist.get_uid(config)
            )


        def pytest_configure_node(node):
            Path(node.config.rootpath, "at-configure-node.txt").write_text(
                _xdist.get_uid(node.config)
            )
    """)
    pytester.runpytest("-n", "2").assert_outcomes(passed=4)

    # `trylast` puts this after the plugin's own `pytest_configure`, so a UID
    # derived any later than that would still read as "main" here.
    assert (pytester.path / "at-configure.txt").read_text() != "main"
    assert (pytester.path / "at-configure-node.txt").read_text() != "main"
