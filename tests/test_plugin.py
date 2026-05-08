"""Integration tests for the plugin via pytester."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

SIMPLE_TEST = textwrap.dedent("""\
    import matplotlib.pyplot as plt

    def test_simple(snapshot_matplotlib):
        fig, ax = plt.subplots()
        ax.plot([1, 2, 3])
        assert fig == snapshot_matplotlib
""")

PARAMETRIZED_TEST = textwrap.dedent("""\
    import matplotlib.pyplot as plt
    import pytest

    @pytest.mark.parametrize("color", ["red", "blue"])
    def test_colors(snapshot_matplotlib, color):
        fig, ax = plt.subplots()
        ax.plot([1, 2, 3], color=color)
        assert fig == snapshot_matplotlib
""")

MULTI_SNAPSHOT_TEST = textwrap.dedent("""\
    import matplotlib.pyplot as plt

    def test_multi(snapshot_matplotlib):
        fig1, ax = plt.subplots(); ax.plot([1, 2, 3])
        assert fig1 == snapshot_matplotlib
        fig2, ax = plt.subplots(); ax.plot([3, 2, 1])
        assert fig2 == snapshot_matplotlib
        fig3, ax = plt.subplots(); ax.plot([1, 1, 1])
        assert fig3 == snapshot_matplotlib(name="flat")
""")


# ── Update mode ─────────────────────────────────────────────────────────────


def test_update_creates_baseline(pytester: pytest.Pytester) -> None:
    """`--snapshot-update` creates a `.png` under `__snapshots__/<module>/`."""
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    result = pytester.runpytest("--snapshot-update", "-v")
    result.assert_outcomes(passed=1)

    snap_dir = pytester.path / "__snapshots__" / "test_plots"
    assert snap_dir.is_dir()
    assert (snap_dir / "test_simple.png").exists()


def test_update_parametrized(pytester: pytest.Pytester) -> None:
    """Update mode creates one baseline per parametrize combo."""
    pytester.makepyfile(test_plots=PARAMETRIZED_TEST)
    result = pytester.runpytest("--snapshot-update", "-v")
    result.assert_outcomes(passed=2)

    snap_dir = pytester.path / "__snapshots__" / "test_plots"
    pngs = sorted(p.name for p in snap_dir.glob("*.png"))
    assert pngs == ["test_colors[blue].png", "test_colors[red].png"]


def test_update_multi_snapshot(pytester: pytest.Pytester) -> None:
    """Each `== snapshot_matplotlib` in a test creates its own baseline."""
    pytester.makepyfile(test_plots=MULTI_SNAPSHOT_TEST)
    result = pytester.runpytest("--snapshot-update", "-v")
    result.assert_outcomes(passed=1)

    snap_dir = pytester.path / "__snapshots__" / "test_plots"
    pngs = sorted(p.name for p in snap_dir.glob("*.png"))
    assert pngs == ["test_multi.1.png", "test_multi.png", "test_multi[flat].png"]


# ── Comparison pass / fail ──────────────────────────────────────────────────


def test_comparison_pass(pytester: pytest.Pytester) -> None:
    """After update, a rerun without flags passes."""
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    pytester.runpytest("--snapshot-update")
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_comparison_fail_on_changed_figure(pytester: pytest.Pytester) -> None:
    """A modified figure fails comparison."""
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    pytester.makeini("[pytest]\nsnapshot_matplotlib_tolerance = 0.01\n")
    pytester.runpytest("--snapshot-update")

    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt

            def test_simple(snapshot_matplotlib):
                fig, ax = plt.subplots()
                ax.scatter([1, 2, 3], [3, 2, 1], color="red", marker="x")
                assert fig == snapshot_matplotlib
        """)
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)


def test_missing_baseline_fails(pytester: pytest.Pytester) -> None:
    """Without `--snapshot-update`, a missing baseline fails."""
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)


# ── Per-call overrides ──────────────────────────────────────────────────────


def test_per_call_tolerance(pytester: pytest.Pytester) -> None:
    """`snapshot_matplotlib(tolerance=...)` is accepted."""
    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt

            def test_x(snapshot_matplotlib):
                fig, ax = plt.subplots(); ax.plot([1, 2, 3])
                assert fig == snapshot_matplotlib(tolerance=5.0)
        """)
    )
    pytester.runpytest("--snapshot-update")
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_unknown_policy_kwarg_rejected(pytester: pytest.Pytester) -> None:
    """Removed `policy=` kwarg raises a TypeError at call time."""
    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt

            def test_x(snapshot_matplotlib):
                fig, ax = plt.subplots(); ax.plot([1, 2, 3])
                snapshot_matplotlib(policy="image_only")
        """)
    )
    result = pytester.runpytest("-v")
    assert result.ret != 0


def test_unknown_policy_cli_rejected(pytester: pytest.Pytester) -> None:
    """Removed `--snapshot-matplotlib-policy` is unknown at parse time."""
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    result = pytester.runpytest("--snapshot-matplotlib-policy=image_only")
    assert result.ret != 0


# ── remove_text per-call option ──────────────────────────────────────────────


def test_remove_text_option(pytester: pytest.Pytester) -> None:
    """`snapshot_matplotlib(remove_text=True)` strips ticks before serializing."""
    src = textwrap.dedent("""\
        import matplotlib.pyplot as plt

        def test_stripped(snapshot_matplotlib):
            fig, ax = plt.subplots()
            ax.set_title("Title to strip")
            ax.plot([1, 2, 3])
            assert fig == snapshot_matplotlib(remove_text=True)
    """)
    pytester.makepyfile(test_plots=src)
    pytester.runpytest("--snapshot-update", "-v").assert_outcomes(passed=1)
    pytester.runpytest("-v").assert_outcomes(passed=1)


def test_remove_text_ini_default(pytester: pytest.Pytester) -> None:
    """INI `snapshot_matplotlib_remove_text = true` applies without override."""
    pytester.makeini("[pytest]\nsnapshot_matplotlib_remove_text = true\n")
    src = textwrap.dedent("""\
        import matplotlib.pyplot as plt

        def test_default_stripped(snapshot_matplotlib):
            fig, ax = plt.subplots()
            ax.set_title("Title to strip")
            ax.plot([1, 2, 3])
            assert fig == snapshot_matplotlib
    """)
    pytester.makepyfile(test_plots=src)
    pytester.runpytest("--snapshot-update", "-v").assert_outcomes(passed=1)
    pytester.runpytest("-v").assert_outcomes(passed=1)


def test_savefig_kwargs_ini_default(pytester: pytest.Pytester) -> None:
    """INI `snapshot_matplotlib_savefig_kwargs` JSON applies without override."""
    pytester.makeini('[pytest]\nsnapshot_matplotlib_savefig_kwargs = {"dpi": 80}\n')
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    pytester.runpytest("--snapshot-update", "-v").assert_outcomes(passed=1)
    pytester.runpytest("-v").assert_outcomes(passed=1)


# ── Non-Figure operand raises ────────────────────────────────────────────────


def test_non_figure_operand_raises(pytester: pytest.Pytester) -> None:
    """Comparing something that isn't a Figure surfaces a clear error."""
    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            def test_bad(snapshot_matplotlib):
                assert [1, 2, 3] == snapshot_matplotlib
        """)
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)


# ── Unused snapshot detection (syrupy's built-in) ───────────────────────────


def test_unused_snapshot_fails(pytester: pytest.Pytester) -> None:
    """An orphan `.png` in `__snapshots__/` fails without `--snapshot-update`."""
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    pytester.runpytest("--snapshot-update")

    orphan = pytester.path / "__snapshots__" / "test_plots" / "test_orphan.png"
    orphan.write_bytes(b"not a real png but syrupy treats it as a baseline")

    result = pytester.runpytest("-v")
    assert result.ret != 0


def test_png_in_ignore_list_warns(pytester: pytest.Pytester) -> None:
    """Passing `--snapshot-ignore-file-extensions=png` emits a UserWarning."""
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    pytester.runpytest("--snapshot-update")

    result = pytester.runpytest(
        "--snapshot-ignore-file-extensions=png", "-v", "-W", "default"
    )
    result.stderr.fnmatch_lines(["*will not detect unused baselines*"])


def test_unused_snapshot_warn_only(pytester: pytest.Pytester) -> None:
    """`--snapshot-warn-unused` downgrades orphans to warnings."""
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    pytester.runpytest("--snapshot-update")

    orphan = pytester.path / "__snapshots__" / "test_plots" / "test_orphan.png"
    orphan.write_bytes(b"whatever")

    result = pytester.runpytest("-v", "--snapshot-warn-unused")
    result.assert_outcomes(passed=1)


# ── Terminal summary ────────────────────────────────────────────────────────


def test_summary_printed_by_default(pytester: pytest.Pytester) -> None:
    """The image counts block appears without any flag."""
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    pytester.runpytest("--snapshot-update")
    result = pytester.runpytest()
    result.stdout.fnmatch_lines([
        "*snapshot-matplotlib*",
        "Images: 1 OK, 0 failed",
    ])


def test_summary_mixed_outcomes(pytester: pytest.Pytester) -> None:
    """One passing + one failing test yields 1 OK / 1 failed image counts."""
    pytester.makeini("[pytest]\nsnapshot_matplotlib_tolerance = 0.01\n")
    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt

            def test_ok(snapshot_matplotlib):
                fig, ax = plt.subplots(); ax.plot([1, 2, 3])
                assert fig == snapshot_matplotlib

            def test_fail(snapshot_matplotlib):
                fig, ax = plt.subplots(); ax.plot([3, 2, 1])
                assert fig == snapshot_matplotlib
        """)
    )
    pytester.runpytest("--snapshot-update")
    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt

            def test_ok(snapshot_matplotlib):
                fig, ax = plt.subplots(); ax.plot([1, 2, 3])
                assert fig == snapshot_matplotlib

            def test_fail(snapshot_matplotlib):
                fig, ax = plt.subplots()
                ax.scatter([1, 2, 3], [9, 8, 7], color="red", marker="x")
                assert fig == snapshot_matplotlib
        """)
    )
    result = pytester.runpytest()
    result.stdout.fnmatch_lines(["Images: 1 OK, 1 failed"])


def test_summary_verbose_lists_tests(pytester: pytest.Pytester) -> None:
    """With -v, each non-empty bucket lists its node ids."""
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    pytester.runpytest("--snapshot-update")
    result = pytester.runpytest("-v")
    result.stdout.fnmatch_lines([
        "*snapshot-matplotlib*",
        "Images: 1 OK, 0 failed",
        "*OK images (1):*",
        "*test_plots.py::test_simple*",
    ])


def test_summary_update_shows_created(pytester: pytest.Pytester) -> None:
    """`--snapshot-update` reports one `created` count."""
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    result = pytester.runpytest("--snapshot-update")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([
        "*snapshot-matplotlib*",
        "Images: 1 created",
    ])


def test_summary_update_verbose_lists(pytester: pytest.Pytester) -> None:
    """`--snapshot-update -v` expands the `created` bucket with node ids."""
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    result = pytester.runpytest("--snapshot-update", "-v")
    result.stdout.fnmatch_lines([
        "Images: 1 created",
        "*Created images (1):*",
        "*test_plots.py::test_simple*",
    ])


def test_summary_hidden_when_no_records(pytester: pytest.Pytester) -> None:
    """No snapshot_matplotlib tests -> no summary block."""
    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            def test_nothing():
                assert 1 + 1 == 2
        """)
    )
    result = pytester.runpytest()
    for line in result.stdout.lines:
        assert "snapshot-matplotlib" not in line or "plugin" in line.lower()


# ── Auto-discovery / auto-assert / auto-close ───────────────────────────────

AUTO_TEST = textwrap.dedent("""\
    import matplotlib.pyplot as plt

    def test_auto(snapshot_matplotlib):
        fig, ax = plt.subplots()
        ax.plot([1, 2, 3])
""")


def test_auto_discovers_and_asserts(pytester: pytest.Pytester) -> None:
    """Unasserted figures are discovered and compared at teardown."""
    pytester.makepyfile(test_plots=AUTO_TEST)
    result = pytester.runpytest("--snapshot-update", "-v")
    result.assert_outcomes(passed=1)

    snap_dir = pytester.path / "__snapshots__" / "test_plots"
    assert (snap_dir / "test_auto.png").exists()

    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_auto_fails_on_changed_figure(pytester: pytest.Pytester) -> None:
    """Auto-asserted figure mismatch is a call-phase failure, not a teardown error.

    A `pytest.fail` in fixture teardown would surface as `errors=1`, which
    is not counted as a test failure by CI. The plugin runs auto-assertions
    via a `pytest_runtest_call` hookwrapper to attribute the failure to the
    call phase instead.
    """
    pytester.makepyfile(test_plots=AUTO_TEST)
    pytester.makeini("[pytest]\nsnapshot_matplotlib_tolerance = 0.01\n")
    pytester.runpytest("--snapshot-update")

    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt

            def test_auto(snapshot_matplotlib):
                fig, ax = plt.subplots()
                ax.scatter([1, 2, 3], [9, 8, 7], color="red", marker="x")
        """)
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1, errors=0)
    result.stdout.fnmatch_lines(["Images: 0 OK, 1 failed"])


def test_missing_baseline_recorded_in_summary(pytester: pytest.Pytester) -> None:
    """A missing baseline counts as a failed image in the summary.

    Syrupy's `_assert` skips `extension.matches()` when no baseline exists
    on disk. Without compensation the comparison record would never be
    written, so the summary would report `0 failed` even though the test
    failed.
    """
    pytester.makepyfile(test_plots=SIMPLE_TEST)
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["Images: 0 OK, 1 failed"])


def test_auto_missing_baseline_recorded_in_summary(pytester: pytest.Pytester) -> None:
    """Auto-asserted figure with no baseline counts in the summary too."""
    pytester.makepyfile(test_plots=AUTO_TEST)
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1, errors=0)
    result.stdout.fnmatch_lines(["Images: 0 OK, 1 failed"])


def test_auto_closes_figures(pytester: pytest.Pytester) -> None:
    """Fixture closes figures it auto-discovered."""
    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt
            from matplotlib._pylab_helpers import Gcf

            def test_auto(snapshot_matplotlib):
                fig, ax = plt.subplots()
                ax.plot([1, 2, 3])

            def test_after_auto():
                assert len(Gcf.figs) == 0
        """)
    )
    result = pytester.runpytest("--snapshot-update", "-v")
    result.assert_outcomes(passed=2)


def test_auto_off_via_call(pytester: pytest.Pytester) -> None:
    """`snapshot_matplotlib(auto=False)` disables auto-assert and auto-close."""
    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import os
            import matplotlib.pyplot as plt
            from matplotlib._pylab_helpers import Gcf

            def test_no_auto(snapshot_matplotlib):
                snapshot_matplotlib(auto=False)
                fig, ax = plt.subplots()
                ax.plot([1, 2, 3])
                os.environ["_FIGNUM"] = str(fig.number)

            def test_still_open():
                num = int(os.environ.pop("_FIGNUM"))
                assert num in Gcf.figs
                plt.close(num)
        """)
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=2)


def test_auto_off_via_ini(pytester: pytest.Pytester) -> None:
    """`snapshot_matplotlib_auto = false` (INI) globally disables auto."""
    pytester.makepyfile(test_plots=AUTO_TEST)
    pytester.makeini("[pytest]\nsnapshot_matplotlib_auto = false\n")
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)


def test_explicit_assertion_not_duplicated(pytester: pytest.Pytester) -> None:
    """Explicitly asserted figures are not re-asserted by auto teardown."""
    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt

            def test_mixed(snapshot_matplotlib):
                fig, ax = plt.subplots()
                ax.plot([1, 2, 3])
                assert fig == snapshot_matplotlib
        """)
    )
    result = pytester.runpytest("--snapshot-update", "-v")
    result.assert_outcomes(passed=1)

    snap_dir = pytester.path / "__snapshots__" / "test_plots"
    pngs = sorted(p.name for p in snap_dir.glob("*.png"))
    assert pngs == ["test_mixed.png"]


def test_auto_ignores_pre_existing_figures(pytester: pytest.Pytester) -> None:
    """Figures open before fixture setup are not auto-asserted or auto-closed."""
    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt
            from matplotlib._pylab_helpers import Gcf

            _PRE_FIG = plt.figure()

            def test_auto(snapshot_matplotlib):
                fig, ax = plt.subplots()
                ax.plot([1, 2, 3])

            def test_pre_fig_still_open():
                assert _PRE_FIG.number in Gcf.figs
                plt.close(_PRE_FIG)
        """)
    )
    result = pytester.runpytest("--snapshot-update", "-v")
    result.assert_outcomes(passed=2)
    snap_dir = pytester.path / "__snapshots__" / "test_plots"
    assert sorted(p.name for p in snap_dir.glob("*.png")) == ["test_auto.png"]


def test_auto_asserts_multiple_figures(pytester: pytest.Pytester) -> None:
    """Multiple unasserted figures all get auto-asserted and auto-closed."""
    pytester.makepyfile(
        test_plots=textwrap.dedent("""\
            import matplotlib.pyplot as plt
            from matplotlib._pylab_helpers import Gcf

            def test_two_figs(snapshot_matplotlib):
                f1, a1 = plt.subplots(); a1.plot([1, 2, 3])
                f2, a2 = plt.subplots(); a2.plot([3, 2, 1])

            def test_after():
                assert len(Gcf.figs) == 0
        """)
    )
    result = pytester.runpytest("--snapshot-update", "-v")
    result.assert_outcomes(passed=2)
    snap_dir = pytester.path / "__snapshots__" / "test_plots"
    pngs = sorted(p.name for p in snap_dir.glob("*.png"))
    assert "test_two_figs.png" in pngs
    assert "test_two_figs.1.png" in pngs
