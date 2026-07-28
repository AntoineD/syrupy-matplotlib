"""Integration tests for per-environment baseline variants.

No test can choose the variant tag: it is derived from the installed
matplotlib, and there is no option, environment variable or flag value that
overrides it. Every variant path here is therefore built from `TAG`, never
from a literal like `mpl-3.10`, which would stop exercising the feature the
day CI bumps matplotlib.
"""

from __future__ import annotations

import json
import textwrap
from importlib.metadata import version as get_distribution_version
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _derive_tag() -> str:
    """Return the variant tag the plugin derives for this environment.

    Deliberately a second implementation of `_config.derive_variant_tag`,
    written from the documented rule rather than imported: importing it
    would make the tests agree with the code by construction.

    Returns:
        `mpl-<major>.<minor>` of the installed matplotlib.
    """
    major, _, rest = get_distribution_version("matplotlib").partition(".")
    return f"mpl-{major}.{rest.partition('.')[0]}"


TAG = _derive_tag()

PIN = "--snapshot-matplotlib-pin-variant"

#: Two visibly different figures. Drawing one or the other from the same test
#: name is how these tests make an environment "render differently".
PLOT_A = textwrap.dedent("""\
    import matplotlib.pyplot as plt

    def test_fig(snapshot_matplotlib):
        fig, ax = plt.subplots()
        ax.plot([1, 2, 3])
        assert fig == snapshot_matplotlib
""")

PLOT_B = textwrap.dedent("""\
    import matplotlib.pyplot as plt

    def test_fig(snapshot_matplotlib):
        fig, ax = plt.subplots()
        ax.scatter([1, 2, 3], [3, 1, 2], color="red", marker="x")
        assert fig == snapshot_matplotlib
""")

PLOT_C = textwrap.dedent("""\
    import matplotlib.pyplot as plt

    def test_fig(snapshot_matplotlib):
        fig, ax = plt.subplots()
        ax.bar([1, 2, 3], [3, 1, 2], color="green")
        assert fig == snapshot_matplotlib
""")

#: A plain syrupy snapshot. Requesting the `snapshot` fixture is what brings
#: syrupy's default extension into the session, and its discovery walks the
#: whole `__snapshots__/` tree rather than one module's directory.
PLAIN_SNAPSHOT = textwrap.dedent("""
    def test_text(snapshot):
        assert "hello" == snapshot
""")

#: A snapshot from another *single-file* `.png` extension, which parks a
#: stranger's baseline right in the module snapshot directory.
PNG_SNAPSHOT = textwrap.dedent("""
    from syrupy.extensions.image import PNGImageSnapshotExtension

    def test_raw(snapshot):
        assert b"not a real png" == snapshot.use_extension(PNGImageSnapshotExtension)
""")

CO_TENANT = PLOT_A + PLAIN_SNAPSHOT
CO_TENANT_VARIANT = PLOT_B + PLAIN_SNAPSHOT
CO_TENANT_PNG = PLOT_A + PNG_SNAPSHOT


def canonical_path(pytester: pytest.Pytester) -> Path:
    """Return the canonical baseline path for the shared one-test module.

    Args:
        pytester: The pytester fixture.

    Returns:
        Path to `__snapshots__/test_plots/test_fig.png`.
    """
    return pytester.path / "__snapshots__" / "test_plots" / "test_fig.png"


def variant_path(pytester: pytest.Pytester, tag: str = TAG) -> Path:
    """Return the variant baseline path for the shared one-test module.

    Args:
        pytester: The pytester fixture.
        tag: Variant tag naming the directory.

    Returns:
        Path to `__snapshots_variants__/<tag>/test_plots/test_fig.png`.
    """
    return (
        pytester.path / "__snapshots_variants__" / tag / "test_plots" / "test_fig.png"
    )


def make_variant(pytester: pytest.Pytester, canonical: str, variant: str) -> None:
    """Set up a module whose canonical and variant baselines differ.

    Renders *canonical* into the canonical baseline, then *variant* into the
    variant baseline through the real generation command, leaving the module
    drawing *variant* — i.e. the state of an environment that renders
    differently from the one the baselines were authored in.

    Args:
        pytester: The pytester fixture.
        canonical: Test source whose figure becomes the canonical baseline.
        variant: Test source whose figure becomes the variant baseline.
    """
    pytester.makepyfile(test_plots=canonical)
    pytester.runpytest("--snapshot-update").assert_outcomes(passed=1)
    pytester.makepyfile(test_plots=variant)
    pytester.runpytest("--snapshot-update", PIN).assert_outcomes(passed=1)


def read_records(pytester: pytest.Pytester) -> dict:
    """Return the `results` mapping of the JSON report.

    Args:
        pytester: The pytester fixture.

    Returns:
        Mapping of record key to record dictionary.
    """
    report = pytester.path / "figure-report" / "results.json"
    return json.loads(report.read_text())["results"]


# ── Comparison runs ─────────────────────────────────────────────────────────


def test_unrelated_variant_directory_ignored(pytester: pytest.Pytester) -> None:
    """A variant directory for another environment is invisible to the run.

    The plugin accounts for the tag directory of the environment it runs in
    and for nothing else — no other tag is reported, rewritten or deleted,
    whether or not this environment has variants of its own.
    """
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.runpytest("--snapshot-update")
    stray = variant_path(pytester, "mpl-0.1")
    stray.parent.mkdir(parents=True)
    stray.write_bytes(canonical_path(pytester).read_bytes())

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)
    result.stdout.no_fnmatch_line("*unused*")
    assert stray.exists()


def test_directory_below_the_module_directory_ignored(
    pytester: pytest.Pytester,
) -> None:
    """A `.png` in a subdirectory of the module directory is not accounted for.

    Variants used to live at `__snapshots__/<module>/<tag>/`, so a suite
    upgrading from that layout still has such directories. They are not
    reported as unused (which would fail the run) and not deleted; removing
    them is a `git rm`.
    """
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.runpytest("--snapshot-update")
    legacy = canonical_path(pytester).parent / TAG / "test_fig.png"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(canonical_path(pytester).read_bytes())

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)
    result.stdout.no_fnmatch_line("*unused*")
    assert result.ret == 0
    assert legacy.exists()


def test_variants_live_outside_the_snapshot_directory(
    pytester: pytest.Pytester,
) -> None:
    """Variants live in their own root, not under `__snapshots__/`.

    Pins the layout itself, which the rest of this module reaches only through
    `variant_path`. Everything under `__snapshots__/` is syrupy's to account
    for, and a variant describing another environment is unused there by
    definition — see the two tests below.
    """
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)

    assert (
        pytester.path / "__snapshots_variants__" / TAG / "test_plots" / "test_fig.png"
    ).exists()
    assert not (pytester.path / "__snapshots__" / TAG).exists()
    assert not (pytester.path / "__snapshots__" / "test_plots" / TAG).exists()


@pytest.mark.parametrize("source", [CO_TENANT, CO_TENANT_PNG])
def test_plain_snapshots_leave_a_foreign_variant_alone(
    pytester: pytest.Pytester, source: str
) -> None:
    """Another environment's variant survives a suite with ordinary snapshots.

    Requesting the `snapshot` fixture puts syrupy's default extension in the
    session, and it discovers every file under `__snapshots__/`; a single-file
    `.png` extension discovers `__snapshots__/test_plots/`. Neither knows about
    variants, so a variant stored below either root was reported as *its*
    unused snapshot — failing a run whose every test passed — and deleted by
    the next `--snapshot-update`.
    """
    pytester.makepyfile(test_plots=source)
    pytester.runpytest("--snapshot-update").assert_outcomes(passed=2)
    foreign = variant_path(pytester, "mpl-0.1")
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(canonical_path(pytester).read_bytes())

    result = pytester.runpytest()

    result.assert_outcomes(passed=2)
    result.stdout.no_fnmatch_line("*unused*")
    assert result.ret == 0

    pytester.runpytest("--snapshot-update").assert_outcomes(passed=2)

    assert foreign.exists(), "another environment's variant was deleted"


def test_plain_snapshots_do_not_flag_a_shadowed_canonical(
    pytester: pytest.Pytester,
) -> None:
    """Reading a variant still counts as using the canonical baseline.

    Syrupy records the location handed out by `get_location` as the snapshot
    the run used, and reports every other file under `__snapshots__/` as
    unused — which fails the session. Naming the variant there left the
    canonical baseline of every snapshot this environment has a variant for
    looking abandoned.
    """
    pytester.makepyfile(test_plots=CO_TENANT)
    pytester.runpytest("--snapshot-update").assert_outcomes(passed=2)
    pytester.makepyfile(test_plots=CO_TENANT_VARIANT)
    pytester.runpytest("--snapshot-update", PIN).assert_outcomes(passed=2)
    assert variant_path(pytester).exists()

    result = pytester.runpytest()

    result.assert_outcomes(passed=2)
    result.stdout.fnmatch_lines([f"Images: 1 OK, 0 failed (variant baselines: {TAG})"])
    result.stdout.no_fnmatch_line("*unused*")
    assert result.ret == 0
    assert canonical_path(pytester).exists()


def test_variant_preferred_over_canonical(pytester: pytest.Pytester) -> None:
    """The variant baseline wins when it exists, and the report says so."""
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)

    result = pytester.runpytest("--snapshot-matplotlib-report=json")

    result.assert_outcomes(passed=1)
    (record,) = read_records(pytester).values()
    assert record["baseline_variant"] == TAG


def test_fallback_to_canonical(pytester: pytest.Pytester) -> None:
    """With no variant file, the canonical baseline is used and passes."""
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.runpytest("--snapshot-update")

    result = pytester.runpytest("--snapshot-matplotlib-report=json")

    result.assert_outcomes(passed=1)
    assert not variant_path(pytester).exists()
    (record,) = read_records(pytester).values()
    assert record["baseline_variant"] is None


@pytest.mark.parametrize("explicit", [True, False])
def test_fallback_failure_reports_canonical(
    pytester: pytest.Pytester, explicit: bool
) -> None:
    """No variant plus a mismatching canonical fails against the canonical.

    Parametrized over the explicit `assert fig == snapshot_matplotlib` and
    the auto-assert paths, which reach `matches()` through different call
    sites.

    Args:
        pytester: The pytester fixture.
        explicit: Whether the test asserts explicitly or relies on auto-assert.
    """
    source = (
        PLOT_A
        if explicit
        else PLOT_A.replace("        assert fig == snapshot_matplotlib\n", "")
    )
    pytester.makepyfile(test_plots=source)
    pytester.runpytest("--snapshot-update")
    changed = (
        PLOT_B
        if explicit
        else PLOT_B.replace("        assert fig == snapshot_matplotlib\n", "")
    )
    pytester.makepyfile(test_plots=changed)

    result = pytester.runpytest("--snapshot-matplotlib-report=json")

    result.assert_outcomes(failed=1)
    (record,) = read_records(pytester).values()
    assert record["baseline_variant"] is None
    assert record["image_status"] == "diff"


@pytest.mark.parametrize("explicit", [True, False])
def test_variant_preferred_on_both_assertion_paths(
    pytester: pytest.Pytester, explicit: bool
) -> None:
    """Auto-assert honors the variant exactly as the explicit path does.

    Args:
        pytester: The pytester fixture.
        explicit: Whether the test asserts explicitly or relies on auto-assert.
    """
    strip = "        assert fig == snapshot_matplotlib\n"
    canonical = PLOT_A if explicit else PLOT_A.replace(strip, "")
    variant = PLOT_B if explicit else PLOT_B.replace(strip, "")
    make_variant(pytester, canonical=canonical, variant=variant)

    pytester.runpytest().assert_outcomes(passed=1)


def test_variant_mismatch_fails_against_variant(pytester: pytest.Pytester) -> None:
    """A figure matching neither baseline fails against the variant."""
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)
    pytester.makepyfile(test_plots=PLOT_C)

    result = pytester.runpytest("--snapshot-matplotlib-report=json")

    result.assert_outcomes(failed=1)
    (record,) = read_records(pytester).values()
    assert record["baseline_variant"] == TAG


def test_both_baselines_missing(pytester: pytest.Pytester) -> None:
    """No variant and no canonical fails as a missing baseline."""
    pytester.makepyfile(test_plots=PLOT_A)

    result = pytester.runpytest("--snapshot-matplotlib-report=json")

    result.assert_outcomes(failed=1)
    (record,) = read_records(pytester).values()
    assert record["image_status"] == "missing"


def test_variant_without_canonical_fails_a_comparison_run(
    pytester: pytest.Pytester,
) -> None:
    """A variant whose canonical baseline is gone fails instead of passing.

    The variant satisfies the read, so the comparison passed and the run said
    nothing: a baseline had been lost, the variant shadowing it could no
    longer be regenerated (a pin run compares against the canonical), and
    every environment without that variant was failing meanwhile.
    """
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)
    canonical_path(pytester).unlink()

    result = pytester.runpytest()

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines([
        f"*canonical baseline missing for 'test_fig'.*shadows it at *{TAG}*"
    ])


def test_tolerance_respected_on_canonical_fallback(
    pytester: pytest.Pytester,
) -> None:
    """A sub-tolerance canonical difference passes without any variant."""
    pytester.makeini("[pytest]\nsnapshot_matplotlib_tolerance = 100\n")
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.runpytest("--snapshot-update")
    pytester.makepyfile(test_plots=PLOT_B)

    result = pytester.runpytest()

    result.assert_outcomes(passed=1)
    assert not variant_path(pytester).exists()


# ── Update runs ─────────────────────────────────────────────────────────────


def test_variant_created_leaving_canonical_intact(
    pytester: pytest.Pytester,
) -> None:
    """Pinning writes the variant and does not touch the canonical bytes."""
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.runpytest("--snapshot-update")
    canonical_bytes = canonical_path(pytester).read_bytes()
    pytester.makepyfile(test_plots=PLOT_B)

    result = pytester.runpytest("--snapshot-update", PIN)

    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["Images: 1 created"])
    result.stdout.no_fnmatch_line("*Can not relate snapshot location*")
    assert variant_path(pytester).exists()
    assert canonical_path(pytester).read_bytes() == canonical_bytes


def test_stale_variant_deleted(pytester: pytest.Pytester) -> None:
    """A variant the environment no longer needs is removed, canonical kept.

    The deletion is listed by record key, like every other bucket: a bare
    stem would be ambiguous the moment two modules declare a test of the
    same name.
    """
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)
    canonical_bytes = canonical_path(pytester).read_bytes()
    # This environment now renders what the canonical baseline holds.
    pytester.makepyfile(test_plots=PLOT_A)

    result = pytester.runpytest("--snapshot-update", PIN, "-v")

    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([
        "*1 variant deleted*",
        "*Deleted variant images (1):*",
        "    test_plots.py::test_fig::test_fig",
    ])
    assert not variant_path(pytester).exists()
    assert canonical_path(pytester).read_bytes() == canonical_bytes


def test_emptied_variant_directory_is_removed(pytester: pytest.Pytester) -> None:
    """Deleting the last variant takes its tag directory with it.

    An empty `mpl-<x>.<y>/` is not "an environment with variants", and a pin
    run that writes nothing never creates one — leaving it behind would make
    the next canonical re-baseline warn about variants that no longer exist.
    """
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)
    pytester.makepyfile(test_plots=PLOT_A)

    pytester.runpytest("--snapshot-update", PIN).assert_outcomes(passed=1)

    assert not variant_path(pytester).parent.exists()
    assert not variant_path(pytester).parent.parent.exists(), (
        "the tag directory outlived the last module it held variants for"
    )

    pytester.makepyfile(test_plots=PLOT_C)
    result = pytester.runpytest("--snapshot-update")

    result.assert_outcomes(passed=1)
    result.stdout.no_fnmatch_line("*may now be stale*")


def test_empty_variant_directory_is_not_stale(pytester: pytest.Pytester) -> None:
    """A tag directory holding no baseline is not warned about.

    Guards the check independently of the deletion path above: the directory
    can also be emptied by hand or by a `git` checkout.
    """
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.runpytest("--snapshot-update")
    variant_path(pytester).parent.mkdir(parents=True)
    pytester.makepyfile(test_plots=PLOT_B)

    result = pytester.runpytest("--snapshot-update")

    result.assert_outcomes(passed=1)
    result.stdout.no_fnmatch_line("*may now be stale*")


def test_stale_warning_scoped_to_the_rewritten_directory(
    pytester: pytest.Pytester,
) -> None:
    """Rewriting one module does not warn about another module's variants.

    The tags are collected from the snapshot directory being overwritten, so
    a module with no variants next to it stays silent no matter what sits in
    a sibling module's snapshot directory.
    """
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)
    # Back to the canonical render, so the updates below rewrite nothing here.
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.makepyfile(test_other=PLOT_A)
    pytester.runpytest("--snapshot-update").assert_outcomes(passed=2)
    # Only the module without variants renders something else from here on.
    pytester.makepyfile(test_other=PLOT_C)

    result = pytester.runpytest("--snapshot-update")

    result.assert_outcomes(passed=2)
    result.stdout.fnmatch_lines(["Images: 1 OK, 0 failed, 1 created"])
    result.stdout.no_fnmatch_line("*may now be stale*")
    assert variant_path(pytester).exists()


def test_pin_run_clears_orphaned_variants(pytester: pytest.Pytester) -> None:
    """A variant whose test is gone is dropped by the next pin run.

    No assertion can report it — the test that owned it no longer runs — so a
    variant-writing run sweeps the tag directory for variants left without a
    canonical baseline, which is what makes them unusable.
    """
    two_tests = textwrap.dedent("""\
        import matplotlib.pyplot as plt
        import pytest

        @pytest.mark.parametrize("n", [1, 2])
        def test_fig(snapshot_matplotlib, n):
            fig, ax = plt.subplots()
            ax.plot([1, 2, 3]) if n == 1 else ax.scatter([1, 2], [2, 1])
            assert fig == snapshot_matplotlib
    """)
    pytester.makepyfile(test_plots=two_tests)
    pytester.runpytest("--snapshot-update").assert_outcomes(passed=2)
    pytester.makepyfile(
        test_plots=two_tests.replace(
            "ax.scatter([1, 2], [2, 1])", "ax.bar([1, 2], [2, 1])"
        )
    )
    pytester.runpytest("--snapshot-update", PIN).assert_outcomes(passed=2)
    orphan = variant_path(pytester).parent / "test_fig[2].png"
    assert orphan.exists()
    # Retire the second parametrization.
    pytester.makepyfile(
        test_plots=two_tests.replace("[1, 2]", "[1]", 1).replace(
            "ax.plot([1, 2, 3]) if n == 1 else ax.scatter([1, 2], [2, 1])",
            "ax.plot([1, 2, 3])",
        )
    )
    pytester.runpytest("--snapshot-update").assert_outcomes(passed=1)
    assert orphan.exists(), "a canonical re-baseline must leave variants alone"

    result = pytester.runpytest("--snapshot-update", PIN)

    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([
        "Deleted 1 orphaned variant baseline (no canonical baseline left):"
    ])
    # Not through `fnmatch_lines`: a parametrize id makes the path a glob.
    assert str(orphan) in result.stdout.str()
    assert not orphan.exists()


def test_matching_canonical_writes_nothing(pytester: pytest.Pytester) -> None:
    """Pinning an unchanged figure creates no variant directory at all."""
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.runpytest("--snapshot-update")

    result = pytester.runpytest("--snapshot-update", PIN)

    result.assert_outcomes(passed=1)
    assert not variant_path(pytester).parent.exists()


def test_variant_generation_is_idempotent(pytester: pytest.Pytester) -> None:
    """Re-pinning an unchanged variant reports OK, not a creation."""
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)
    variant_bytes = variant_path(pytester).read_bytes()

    result = pytester.runpytest("--snapshot-update", PIN)

    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["Images: 1 OK, 0 failed*"])
    result.stdout.no_fnmatch_line("*created*")
    assert variant_path(pytester).read_bytes() == variant_bytes


def test_pin_run_leaves_no_stray_artifacts(pytester: pytest.Pytester) -> None:
    """Without a report, a variant-writing run leaves nothing in figure-report.

    The canonical comparison behind the write decision produces
    actual/expected/diff files; no record references them, so they must not
    outlive the run.
    """
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.runpytest("--snapshot-update")
    pytester.makepyfile(test_plots=PLOT_B)

    result = pytester.runpytest("--snapshot-update", PIN)

    result.assert_outcomes(passed=1)
    assert variant_path(pytester).exists()
    assert not (pytester.path / "figure-report").exists()


def test_pin_over_a_resized_canonical_writes_a_variant(
    pytester: pytest.Pytester,
) -> None:
    """A figsize change makes the canonical comparison a shape mismatch.

    `compare_images` raises instead of returning an RMS there, so the result
    carries no diff image. The pin run must still read it as "differs", write
    the variant, and clean up the partial artifact set behind it.
    """
    pytester.makepyfile(
        test_plots=PLOT_A.replace("plt.subplots()", "plt.subplots(figsize=(3, 3))")
    )
    pytester.runpytest("--snapshot-update").assert_outcomes(passed=1)
    pytester.makepyfile(
        test_plots=PLOT_A.replace("plt.subplots()", "plt.subplots(figsize=(5, 4))")
    )

    result = pytester.runpytest("--snapshot-update", PIN)

    result.assert_outcomes(passed=1)
    assert variant_path(pytester).exists()
    assert not (pytester.path / "figure-report").exists()


def test_pin_report_shows_the_canonical_comparison(
    pytester: pytest.Pytester,
) -> None:
    """With a report, the GENERATED record carries the canonical comparison.

    The images show what the variant answers; the mismatch message is
    dropped, since a generated baseline is not a failure.
    """
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.runpytest("--snapshot-update")
    pytester.makepyfile(test_plots=PLOT_B)

    result = pytester.runpytest(
        "--snapshot-update", PIN, "--snapshot-matplotlib-report=json"
    )

    result.assert_outcomes(passed=1)
    (record,) = read_records(pytester).values()
    assert record["image_status"] == "generated"
    assert record["rms"] is not None
    assert record["result_image"] is not None
    assert record["baseline_image"] is not None
    assert record["error_message"] is None
    assert record["baseline_variant"] is None


def test_missing_canonical_refuses_to_pin(pytester: pytest.Pytester) -> None:
    """A snapshot cannot exist as a variant only."""
    pytester.makepyfile(test_plots=PLOT_A)

    result = pytester.runpytest("--snapshot-update", PIN)

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*canonical baseline missing*"])
    assert not canonical_path(pytester).exists()
    assert not variant_path(pytester).parent.exists()


def test_missing_canonical_with_existing_variant_refuses(
    pytester: pytest.Pytester,
) -> None:
    """Deleting the canonical does not let its variant live on alone.

    The variant satisfies the baseline read, so without the read-time check
    this run passed silently (the render is byte-equal to the variant) and
    left a variant-only snapshot behind — failing every other environment.
    """
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)
    canonical_path(pytester).unlink()
    variant_bytes = variant_path(pytester).read_bytes()

    result = pytester.runpytest("--snapshot-update", PIN)

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*canonical baseline missing*"])
    result.stdout.no_fnmatch_line("*created*")
    assert variant_path(pytester).read_bytes() == variant_bytes


def test_sub_tolerance_difference_writes_no_variant(
    pytester: pytest.Pytester,
) -> None:
    """A difference the tolerance absorbs is not worth a variant file."""
    pytester.makeini("[pytest]\nsnapshot_matplotlib_tolerance = 100\n")
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.runpytest("--snapshot-update")
    pytester.makepyfile(test_plots=PLOT_B)

    result = pytester.runpytest("--snapshot-update", PIN)

    result.assert_outcomes(passed=1)
    assert not variant_path(pytester).parent.exists()


def test_update_without_the_flag_leaves_variants_alone(
    pytester: pytest.Pytester,
) -> None:
    """A canonical re-baseline neither deletes nor rewrites variants.

    Before the `discover_snapshots` override this printed
    `1 unused snapshot deleted` and unlinked the variant.
    """
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)
    variant_bytes = variant_path(pytester).read_bytes()
    pytester.makepyfile(test_plots=PLOT_C)

    result = pytester.runpytest("--snapshot-update")

    result.assert_outcomes(passed=1)
    result.stdout.no_fnmatch_line("*unused snapshot*")
    result.stdout.fnmatch_lines([f"*variant baselines for {TAG} may now be stale*"])
    assert variant_path(pytester).read_bytes() == variant_bytes


def test_stale_warning_ignores_unrelated_directories(
    pytester: pytest.Pytester,
) -> None:
    """Only directories shaped like a variant tag are reported stale."""
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)
    (pytester.path / "__snapshots__" / "test_plots" / "archive").mkdir()
    pytester.makepyfile(test_plots=PLOT_C)

    result = pytester.runpytest("--snapshot-update")

    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([f"*variant baselines for {TAG} may now be stale*"])
    result.stdout.no_fnmatch_line("*archive*")


def test_no_stale_warning_when_nothing_rewritten(pytester: pytest.Pytester) -> None:
    """An idempotent `--snapshot-update` does not cry stale.

    The warning says "canonical baselines rewritten"; a run whose figures
    all match the canonical baselines rewrote nothing.
    """
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)
    pytester.makepyfile(test_plots=PLOT_A)

    result = pytester.runpytest("--snapshot-update")

    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["Images: 1 OK, 0 failed"])
    result.stdout.no_fnmatch_line("*may now be stale*")


def test_pinning_does_not_flag_canonical_unused(pytester: pytest.Pytester) -> None:
    """A variant-writing run counts the canonical baselines it read as used.

    Mirror of the previous test, on the mode that would lose the most: syrupy
    deletes what it reports unused when updating, so a pin run that named
    variant locations as the snapshots it used would delete the canonical
    baselines it exists to compare against.
    """
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)

    result = pytester.runpytest("--snapshot-update", PIN)

    result.assert_outcomes(passed=1)
    result.stdout.no_fnmatch_line("*unused snapshot*")
    assert canonical_path(pytester).exists()


def test_last_failed_narrows_generation(pytester: pytest.Pytester) -> None:
    """`--lf` writes variants for the failing tests only."""
    two_tests = textwrap.dedent("""\
        import matplotlib.pyplot as plt
        import pytest

        @pytest.mark.parametrize("n", [1, 2])
        def test_fig(snapshot_matplotlib, n):
            fig, ax = plt.subplots()
            ax.plot([1, 2, 3])
            assert fig == snapshot_matplotlib
    """)
    pytester.makepyfile(test_plots=two_tests)
    pytester.runpytest("--snapshot-update").assert_outcomes(passed=2)
    # Only the second parametrization renders something else from here on.
    pytester.makepyfile(
        test_plots=two_tests.replace(
            "ax.plot([1, 2, 3])",
            "ax.plot([1, 2, 3]) if n == 1 else ax.scatter([1, 2], [2, 1])",
        )
    )
    pytester.runpytest().assert_outcomes(passed=1, failed=1)

    result = pytester.runpytest("--snapshot-update", PIN, "--lf")

    result.assert_outcomes(passed=1)
    variant_dir = variant_path(pytester).parent
    assert [p.name for p in variant_dir.iterdir()] == ["test_fig[2].png"]


# ── Derivation, flag errors, header ─────────────────────────────────────────


def test_tag_follows_installed_matplotlib(pytester: pytest.Pytester) -> None:
    """The directory is named after the installed matplotlib, nothing else."""
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.runpytest("--snapshot-update")
    pytester.makepyfile(test_plots=PLOT_B)

    result = pytester.runpytest("--snapshot-update", PIN)

    result.stdout.fnmatch_lines([f"snapshot-matplotlib: environment '{TAG}'*"])
    assert variant_path(pytester).exists()


def test_pin_without_update_is_an_error(pytester: pytest.Pytester) -> None:
    """Pinning is a modifier on `--snapshot-update`, not a mode of its own."""
    pytester.makepyfile(test_plots=PLOT_A)

    result = pytester.runpytest(PIN)

    result.stderr.fnmatch_lines([f"*{PIN}*--snapshot-update*"])
    assert result.ret != 0


def test_pin_refuses_xdist(pytester: pytest.Pytester) -> None:
    """Variant generation is single-process by construction.

    Redundant-variant deletions and their reporting are per-worker
    bookkeeping that would silently vanish from the controller's summary.
    """
    pytester.makepyfile(test_plots=PLOT_A)

    result = pytester.runpytest("--snapshot-update", PIN, "-n", "2")

    assert result.ret != 0
    result.stderr.fnmatch_lines([f"*{PIN} does not run under pytest-xdist*"])


def test_header_absent_without_pinning(pytester: pytest.Pytester) -> None:
    """A comparison run says nothing in the header.

    The tag is only interesting when the run acts on it; a suite that never
    renders a figure must not gain a header line from having the plugin
    installed.
    """
    pytester.makepyfile(test_plots=PLOT_A)
    pytester.runpytest("--snapshot-update")

    result = pytester.runpytest()

    result.stdout.no_fnmatch_line("*environment*pinning*")
    result.stdout.no_fnmatch_line("*snapshot-matplotlib: environment*")


def test_summary_names_the_variant_actually_used(pytester: pytest.Pytester) -> None:
    """A comparison that reads a variant says so in the summary line."""
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)

    result = pytester.runpytest()

    result.stdout.fnmatch_lines([f"Images: 1 OK, 0 failed (variant baselines: {TAG})"])


# ── xdist ───────────────────────────────────────────────────────────────────


def test_variant_read_under_xdist(pytester: pytest.Pytester) -> None:
    """Variant lookup works on workers, which is what CI actually runs."""
    two_tests = textwrap.dedent("""\
        import matplotlib.pyplot as plt
        import pytest

        @pytest.mark.parametrize("n", [1, 2])
        def test_fig(snapshot_matplotlib, n):
            fig, ax = plt.subplots()
            ax.plot([1, 2, 3]) if n == 1 else ax.scatter([1, 2], [2, 1])
            assert fig == snapshot_matplotlib
    """)
    pytester.makepyfile(test_plots=two_tests)
    pytester.runpytest("--snapshot-update", "-p", "no:xdist")
    # Give only the second parametrization a variant baseline.
    pytester.makepyfile(
        test_plots=two_tests.replace(
            "ax.scatter([1, 2], [2, 1])", "ax.bar([1, 2], [2, 1])"
        )
    )
    pytester.runpytest("--snapshot-update", PIN, "-p", "no:xdist")

    result = pytester.runpytest("-n", "2")

    result.assert_outcomes(passed=2)
    result.stdout.no_fnmatch_line("*unused snapshot*")
