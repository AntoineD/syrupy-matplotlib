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
        tag: Variant tag naming the subdirectory.

    Returns:
        Path to `__snapshots__/test_plots/<tag>/test_fig.png`.
    """
    return pytester.path / "__snapshots__" / "test_plots" / tag / "test_fig.png"


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

    Regression pin for the `discover_snapshots` override: syrupy's
    `walk_snapshot_dir` recurses, so without it the stray file is reported
    as an unused snapshot, which fails the session.
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
    """A variant the environment no longer needs is removed, canonical kept."""
    make_variant(pytester, canonical=PLOT_A, variant=PLOT_B)
    canonical_bytes = canonical_path(pytester).read_bytes()
    # This environment now renders what the canonical baseline holds.
    pytester.makepyfile(test_plots=PLOT_A)

    result = pytester.runpytest("--snapshot-update", PIN, "-v")

    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([
        "*1 variant deleted*",
        "*Deleted variant images (1):*",
    ])
    assert not variant_path(pytester).exists()
    assert canonical_path(pytester).read_bytes() == canonical_bytes


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


def test_missing_canonical_refuses_to_pin(pytester: pytest.Pytester) -> None:
    """A snapshot cannot exist as a variant only."""
    pytester.makepyfile(test_plots=PLOT_A)

    result = pytester.runpytest("--snapshot-update", PIN)

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*canonical baseline missing*"])
    assert not canonical_path(pytester).exists()
    assert not variant_path(pytester).parent.exists()


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


def test_pinning_does_not_flag_canonical_unused(pytester: pytest.Pytester) -> None:
    """Writing variants leaves the canonical baselines out of unused accounting.

    Mirror of the previous test: in variant-writing mode syrupy's `used` set
    holds only variant locations, so an unfiltered discovery would report
    every canonical baseline as unused and delete it.
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
