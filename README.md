# syrupy-matplotlib

[![ci](https://github.com/AntoineD/syrupy-matplotlib/actions/workflows/ci.yml/badge.svg)](https://github.com/AntoineD/syrupy-matplotlib/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/AntoineD/syrupy-matplotlib/branch/main/graph/badge.svg)](https://codecov.io/gh/AntoineD/syrupy-matplotlib)
[![PyPI](https://img.shields.io/pypi/v/syrupy-matplotlib.svg)](https://pypi.org/project/syrupy-matplotlib/)
[![Python versions](https://img.shields.io/pypi/pyversions/syrupy-matplotlib.svg)](https://pypi.org/project/syrupy-matplotlib/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A pytest plugin for comparing matplotlib figures against stored baselines,
built on [syrupy](https://github.com/syrupy-project/syrupy).

> Built with the help of [Claude Code](https://www.claude.com/product/claude-code),
> Anthropic's CLI for Claude. Design, implementation, and tests were
> developed in collaboration with the assistant; the human author reviewed,
> validated, and approved most changes.

Figures are compared through a dedicated `snapshot_matplotlib` fixture using
`assert fig == snapshot_matplotlib`. Syrupy's built-in `snapshot` fixture is
**not shadowed**, so you can keep using it for strings, dicts, JSON, etc. in
the same test suite (or even the same test).

Multiple snapshots per test are supported via auto-indexing or explicit names.

By default the fixture also **auto-discovers, auto-asserts, and auto-closes**
any figures created during a test that were not asserted explicitly — so
tests usually need no `assert` at all.

## Installation

```bash
pip install syrupy-matplotlib
```

Syrupy is installed automatically as a dependency.

## Quick start

```python
import matplotlib.pyplot as plt


def test_sine_wave(snapshot_matplotlib):
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [0, 1, 0])
    # No assert needed — auto-discovered, auto-asserted, auto-closed.
```

Explicit assertions still work and take precedence over auto:

```python
def test_sine_wave(snapshot_matplotlib):
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [0, 1, 0])
    assert fig == snapshot_matplotlib
```

```bash
# Generate baselines
pytest --snapshot-update

# Compare against baselines (default behaviour)
pytest
```

Baselines live in `__snapshots__/<module_stem>/` next to the test module:

```text
tests/
    test_plots.py
    __snapshots__/
        test_plots/
            test_sine_wave.png
```

## Coexistence with syrupy's `snapshot`

The plugin exposes its own `snapshot_matplotlib` fixture and leaves syrupy's
`snapshot` alone. Mix both freely:

```python
def test_metadata_and_figure(snapshot, snapshot_matplotlib):
    assert {"version": 2, "items": 3} == snapshot  # → amber .ambr
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3])
    assert fig == snapshot_matplotlib  # → .png
```

Amber baselines land in `__snapshots__/<module>.ambr`; figure baselines land
in `__snapshots__/<module>/<name>.png`. They never collide.

## Multiple snapshots per test

Each `== snapshot_matplotlib` in a test creates its own baseline. Auto-indexed
by default, overridable with `name=`:

```python
def test_views(snapshot_matplotlib):
    fig1, _ = plt.subplots()  # → test_views.png
    assert fig1 == snapshot_matplotlib

    fig2, _ = plt.subplots()  # → test_views.1.png
    assert fig2 == snapshot_matplotlib

    fig3, _ = plt.subplots()  # → test_views[zoomed].png
    assert fig3 == snapshot_matplotlib(name="zoomed")
```

In a non-parametrized test, the first auto-indexed baseline has no suffix
(`test_views.png`); subsequent ones start at `.1` (`test_views.1.png`,
`test_views.2.png`, ...).

## Per-call overrides

`snapshot_matplotlib(...)` accepts overrides that apply to one assertion only:

```python
def test_loose(snapshot_matplotlib):
    fig, _ = plt.subplots()
    assert fig == snapshot_matplotlib(
        tolerance=5.0,  # RMS threshold
        remove_text=True,  # strip ticks/titles before comparing
        savefig_kwargs={"dpi": 150},
    )
```

Test-scoped defaults (`style`, `backend`) come from INI; override them
globally with a wrapper fixture in `conftest.py` if needed.

## Auto-discover / auto-assert / auto-close

The fixture tracks every figure created during the test. At teardown it
compares each figure that was **not** asserted explicitly against its
baseline and closes all figures it discovered.

```python
def test_one_liner(snapshot_matplotlib):
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3])
    # fig is auto-asserted and auto-closed here.
```

Figures you already asserted with `assert fig == snapshot_matplotlib` are
skipped by the auto path (no double-counted baselines) but are still closed.

Disable the auto behavior at two levels (per-test wins over INI):

```python
# Per test (persists for the rest of the test body):
def test_manual(snapshot_matplotlib):
    snapshot_matplotlib(auto=False)
    ...
```

```ini
# Globally via INI:
[pytest]
snapshot_matplotlib_auto = false
```

Accepted boolean literals: `true`/`false`, `yes`/`no`, `on`/`off`, `1`/`0`.

## CLI flags

| Flag | Source | Description |
|---|---|---|
| `--snapshot-update` | syrupy | Regenerate baseline images. |
| `--snapshot-warn-unused` | syrupy | Warn instead of failing on orphan baselines. |
| `--snapshot-details` | syrupy | List unused snapshots in the summary. |
| `--snapshot-matplotlib-report` | this plugin | Generate an HTML report in `figure-report/`. |
| `--snapshot-matplotlib-report=html,json` | this plugin | Select report formats (`html`, `json`, `basic-html`). |

> **Warning:** Passing `--snapshot-ignore-file-extensions=png` silently
> disables figure discovery. The plugin emits a warning if this is detected.

### `figure-report/` contents

Without `--snapshot-matplotlib-report`, only failed comparisons leave
artifacts under `figure-report/`: the rendered output (`<stem>.png`),
the baseline (`<stem>-expected.png`), and a diff (`<stem>-diff.png`)
for `DIFF` outcomes; just the rendered output for `MISSING` outcomes.
Passing comparisons write nothing.

If at least one comparison fails on a normal run (no
`--snapshot-matplotlib-report`, no `--snapshot-update`), the plugin
also emits `figure-report/report.html` and `figure-report/styles.css`
containing **only** the failed cases — so a failing run gives you a
rendered overview by default. All-pass runs and `--snapshot-update`
runs write no report.

With `--snapshot-matplotlib-report=...`, every comparison's actual and
baseline images are kept so the report can show pass cards as well, and
the chosen `report.html` / `report-basic.html` / `results.json` files
are written alongside (overriding the failed-only default).

## INI options

The values shown below are the defaults applied when no option is set:

```ini
[pytest]
snapshot_matplotlib_tolerance      = 0
snapshot_matplotlib_style          = default
snapshot_matplotlib_backend        = agg
snapshot_matplotlib_auto           = true
snapshot_matplotlib_remove_text    = false
snapshot_matplotlib_savefig_kwargs = {}
```

`snapshot_matplotlib_savefig_kwargs` accepts a JSON object whose keys are
forwarded to `Figure.savefig()`. Per-call kwargs
(`snapshot_matplotlib(remove_text=..., savefig_kwargs=...)`) override the
INI defaults.

CLI flags override INI options.

## Relation to `matplotlib.testing`

The defaults align with `matplotlib.testing.decorators.image_comparison`
where it makes sense — same `tolerance = 0`, same `remove_text = False`,
same `agg` backend, same effective `savefig` rcParams. Two intentional
deviations:

- **Style.** mpl's test suite uses `("classic", "_classic_test_patch")`.
  The `_classic_test_patch.mplstyle` sets `text.kerning_factor = 6` and
  `ytick.alignment = center_baseline`, restoring pre-3.2 glyph metrics
  so mpl's vendored baseline PNGs keep matching across releases. This
  plugin uses `default` (current mpl built-in defaults): fresh baselines
  compare against themselves, so the patch is irrelevant — it only
  matters for byte-parity with mpl's own upstream baseline fixtures.

- **FreeType version pin.** `image_comparison(..., freetype_version=...)`
  skips a test when the installed FreeType differs from the version the
  baseline was rendered against, since glyph anti-aliasing varies
  sub-pixel between FreeType releases. This plugin does not expose an
  equivalent option. In practice, mpl wheels on PyPI vendor FreeType
  2.6.1, so `pip` / `uv` users share the same version. If you install
  mpl from source or via conda-forge (which links the system FreeType),
  text-heavy figures may RMS-drift across machines; either regenerate
  baselines on the target environment or use `remove_text = true`.

## Parametrized tests

Parametrize works without any special configuration. Each combination gets
its own baseline file:

```python
import pytest


@pytest.mark.parametrize("color", ["red", "blue"])
def test_colors(snapshot_matplotlib, color):
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3], color=color)
    assert fig == snapshot_matplotlib
```

Baselines: `test_colors[red].png`, `test_colors[blue].png`.

## Terminal summary

At the end of every run the plugin prints a one-block summary:

```text
=========================== snapshot-matplotlib ============================
Images: 8 OK, 2 failed
```

With `-v` (or higher), each non-empty bucket is expanded to list the
pytest node ids that landed in it:

```text
  OK images (8):
    tests/test_plots.py::test_simple
    ...
  Failed images (2):
    tests/test_plots.py::test_drift
```

## Unused-snapshot detection

Inherited from syrupy: at session end, any `.png` in `__snapshots__/` that
was not touched during the run fails the suite. Downgrade to a warning with
`--snapshot-warn-unused`; delete orphans automatically with
`--snapshot-update`.

## Determinism

The `snapshot_matplotlib` fixture wraps the test body in a deterministic
matplotlib environment: forced backend, `matplotlib.testing` font +
reproducibility helpers, SVG hashsalt, `SOURCE_DATE_EPOCH=0`. Figures are
drawn under the configured `style` via
`plt.style.context(..., after_reset=True)`.

## xdist support

Works with `pytest-xdist` (`-n auto`). Workers write per-worker result
fragments; the controller merges them at session end before generating
reports. Syrupy's own unused-snapshot detection is limited under xdist with
`--snapshot-update` — regenerate baselines without xdist when possible.

## Custom fixture wrappers

To set test-scoped defaults (e.g. a different tolerance for one package),
wrap the fixture in a `conftest.py`:

```python
import pytest


@pytest.fixture
def snapshot_matplotlib(snapshot_matplotlib):
    return snapshot_matplotlib(tolerance=5.0)
```
