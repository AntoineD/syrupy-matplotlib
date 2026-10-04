"""Verify syrupy's built-in `snapshot` fixture still works with our plugin.

The plugin adds a `snapshot_matplotlib` fixture without shadowing syrupy's
`snapshot`, so plain-string / dict comparisons continue to use the amber
extension and land in the expected `__snapshots__/<module>.ambr` layout.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_syrupy_snapshot_still_works(pytester: pytest.Pytester) -> None:
    """Installing syrupy-matplotlib does not break `assert "x" == snapshot`."""
    pytester.makepyfile(
        test_strings=textwrap.dedent("""\
            def test_hello(snapshot):
                assert "hello" == snapshot

            def test_dict(snapshot):
                assert {"k": 1, "items": [1, 2, 3]} == snapshot
        """)
    )
    pytester.runpytest("--snapshot-update").assert_outcomes(passed=2)

    # Amber extension emits a single `.ambr` per module next to the test file.
    amber = pytester.path / "__snapshots__" / "test_strings.ambr"
    assert amber.exists()
    assert "hello" in amber.read_text()

    # Second run compares — must pass.
    pytester.runpytest().assert_outcomes(passed=2)


def test_mixed_fixtures_in_one_test(pytester: pytest.Pytester) -> None:
    """Using both `snapshot` and `snapshot_matplotlib` in one test."""
    pytester.makepyfile(
        test_mixed=textwrap.dedent("""\
            import matplotlib.pyplot as plt

            def test_both(snapshot, snapshot_matplotlib):
                assert {"kind": "meta"} == snapshot

                fig, ax = plt.subplots()
                ax.plot([1, 2, 3])
                assert fig == snapshot_matplotlib
        """)
    )
    pytester.runpytest("--snapshot-update").assert_outcomes(passed=1)

    amber = pytester.path / "__snapshots__" / "test_mixed.ambr"
    figure = pytester.path / "__snapshots__" / "test_mixed" / "test_both.png"
    assert amber.exists()
    assert figure.exists()

    pytester.runpytest().assert_outcomes(passed=1)


def test_non_figure_with_snapshot_matplotlib_still_fails(
    pytester: pytest.Pytester,
) -> None:
    """`snapshot_matplotlib` is strictly for Figures — non-Figures fail loudly."""
    pytester.makepyfile(
        test_bad=textwrap.dedent("""\
            def test_bad(snapshot_matplotlib):
                assert "not a figure" == snapshot_matplotlib
        """)
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(failed=1)
