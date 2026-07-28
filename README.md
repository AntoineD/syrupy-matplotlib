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
    __snapshots_variants__/                 # optional, see "Baseline variants"
        mpl-3.10/
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

When the plotting code doesn't return the figure (e.g. a library that
calls `plt.plot` internally), grab the current figure with `plt.gcf()`
to apply per-call overrides — auto mode skips figures already asserted
explicitly:

```python
def test_lib_plot(snapshot_matplotlib):
    some_lib_that_plots()
    assert plt.gcf() == snapshot_matplotlib(tolerance=5.0)
```

> **`remove_text` mutates the figure.** It calls
> `matplotlib.testing.decorators.remove_ticks_and_titles(fig)`, which strips
> tick labels and titles from the figure object itself rather than from a copy
> — the same thing `image_comparison` does. The figure stays stripped
> afterwards, so a second assertion on it, or any inspection after the
> assertion, sees the stripped version.

Test-scoped defaults (`style`, `backend`) come from INI; override them
globally with a wrapper fixture in `conftest.py` if needed.

## Auto-discover / auto-assert / auto-close

The fixture tracks every figure created during the test. At the end of the
test's call phase it compares each figure that was **not** asserted
explicitly against its baseline — so a mismatch is a regular test failure,
not a teardown error — and at teardown it closes all figures it discovered.

```python
def test_one_liner(snapshot_matplotlib):
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3])
    # fig is auto-asserted and auto-closed here.
```

Figures you already asserted with `assert fig == snapshot_matplotlib` are
skipped by the auto path (no double-counted baselines) but are still closed.

> **Auto-discovery only sees pyplot-managed figures.** It reads matplotlib's
> global figure manager, which tracks figures created through `plt.figure()`,
> `plt.subplots()`, and friends. A figure built directly — `fig = Figure()`,
> the usual shape in embedded or library code — is invisible to it and must
> be asserted explicitly:
>
> ```python
> from matplotlib.figure import Figure
>
>
> def test_embedded(snapshot_matplotlib):
>     fig = Figure()
>     fig.subplots().plot([1, 2, 3])
>     assert fig == snapshot_matplotlib  # required: auto won't find it
> ```
>
> A test that requests the fixture, has auto enabled, and ends up comparing
> no figure at all emits a warning rather than passing silently.

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
| `--snapshot-matplotlib-report-dir` | this plugin | Where artifacts and reports land (default `figure-report/`). |
| `--snapshot-matplotlib-pin-variant` | this plugin | With `--snapshot-update`, write [baseline variants](#baseline-variants) for the installed matplotlib instead of rewriting the canonical baselines. |

> **Warning:** Passing `--snapshot-ignore-file-extensions=png` silently
> disables figure discovery. The plugin emits a warning if this is detected.

### The report directory

`figure-report/` is the default; `--snapshot-matplotlib-report-dir=DIR` or
`snapshot_matplotlib_report_dir` moves it. A relative value is resolved
against the rootdir.

> **The plugin owns this directory.** At the start of every session it
> deletes its own reports and every `*.png` beneath it, so a run that goes
> green cannot leave the previous run's failure report standing. Point it at
> a directory of its own — the rootdir itself is rejected.

Give concurrent runs that share a checkout (`tox -p`, two CI jobs) their own
directory: they otherwise write the same artifact paths for the same test
and race on them.

#### Contents

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

> **Note:** Combining a report flag with `--snapshot-update` writes the
> report but **no images** — update mode regenerates baselines instead of
> running comparisons, so there are no actual/baseline/diff artifacts to
> embed. Run the report on a normal comparison run to get image cards.

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
snapshot_matplotlib_report_dir     = figure-report
```

A blank value (`snapshot_matplotlib_remove_text =`) counts as unset for every
option and falls back to the default shown above.

`snapshot_matplotlib_style` accepts a comma-separated list, applied left to
right the way `plt.style.use()` composes styles — `classic,
_classic_test_patch` is matplotlib's own test-suite pairing.

`snapshot_matplotlib_savefig_kwargs` accepts a JSON object whose keys are
forwarded to `Figure.savefig()`. A per-call
`snapshot_matplotlib(savefig_kwargs=...)` **replaces** the INI dict wholesale
rather than merging per key — pass every key you need, including any INI
defaults you want to keep. Per-call `remove_text` / `tolerance` likewise
override the INI defaults for that one assertion.

Precedence runs per-call `snapshot_matplotlib(...)` → `set_defaults()` → INI
→ built-in default. Only `snapshot_matplotlib_report_dir` has a CLI
counterpart, which wins over it; `--snapshot-matplotlib-report` is CLI-only,
and the rest are INI-only.

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
  matters for byte-parity with mpl's own upstream baseline fixtures. Set
  `snapshot_matplotlib_style = classic,_classic_test_patch` to adopt it.

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

The line grows a `(variant baselines: mpl-3.10)` suffix when a comparison
actually read a [baseline variant](#baseline-variants), and a
`N variant deleted` count when a variant-writing run dropped redundant ones.

With `-v` (or higher), each non-empty bucket is expanded to list its
records — the pytest node id plus the snapshot stem, one entry per
assertion:

```text
  OK images (8):
    tests/test_plots.py::test_simple::test_simple
    ...
  Failed images (2):
    tests/test_plots.py::test_drift::test_drift
```

## Unused-snapshot detection

Inherited from syrupy: at session end, any `.png` in `__snapshots__/` that
was not touched during the run fails the suite. Downgrade to a warning with
`--snapshot-warn-unused`; delete orphans automatically with
`--snapshot-update`.

Each run accounts only for the baselines it maintains, so a plain
`--snapshot-update` never reports or deletes [baseline
variants](#baseline-variants), and a variant-writing run never does that to
the canonical baselines.

## Determinism

The `snapshot_matplotlib` fixture wraps the test body in a deterministic
matplotlib environment: forced backend, `matplotlib.testing` font +
reproducibility helpers, SVG hashsalt, `SOURCE_DATE_EPOCH=0`. Figures are
drawn under the configured `style` via
`plt.style.context(..., after_reset=True)`.

Determinism holds **within** a matplotlib version, not across upgrades. The
plugin delegates font setup to `matplotlib.testing`, so whatever that helper
changes, your rendering follows. Concretely, matplotlib 3.11 changed
`set_font_settings_for_testing()` to set `text.hinting = "default"` (it was
`"none"`) and stopped setting `text.hinting_factor`. Glyph rasterization
differs between those two settings, so **baselines containing visible text and
generated under matplotlib ≤ 3.10 will fail against matplotlib ≥ 3.11.**

Treat a matplotlib minor bump like a FreeType change: regenerate with
`--snapshot-update` and eyeball the diff, or insulate the suite with
`remove_text = true` / a non-zero `snapshot_matplotlib_tolerance`.

When the versions have to coexist — a CI matrix whose oldest Python resolves
an older matplotlib — give that environment its own baselines instead. See
the next section.

## Baseline variants

A snapshot can carry an extra baseline for the environment that renders it
differently, and only for the figures that actually differ there. The typical
case is a CI matrix: matplotlib 3.11 requires Python >= 3.11, so the Python
3.10 job resolves matplotlib 3.10 and every comparison fails on the text
hinting change described above.

```text
tests/
    test_plots.py
    __snapshots__/
        test_plots/
            test_sine_wave.png            # canonical baseline
    __snapshots_variants__/
        mpl-3.10/
            test_plots/
                test_sine_wave.png        # used only under matplotlib 3.10
```

**There is nothing to configure, and no CI job needs a special command.** The
directory name is derived from the installed matplotlib
(`mpl-<major>.<minor>`), so every run already knows which one applies. A
comparison reads `__snapshots_variants__/<tag>/<module_stem>/<name>.png` when that
file exists and the canonical baseline otherwise.

Variants sit in their own directory beside `__snapshots__/`, not inside it,
because syrupy accounts for everything under `__snapshots__/`: a file the run
did not use is reported as an unused snapshot — which fails the session even
when every test passed — and deleted by the next `--snapshot-update`. A variant
for *another* environment is unused by definition, so any suite that also uses
syrupy's own `snapshot` fixture would have failed on it and then lost it.

The workflow, on the motivating scenario:

```bash
# 1. Author or re-baseline the canonical images, wherever you work.
pytest --snapshot-update

# 2. In the old environment (pin matplotlib there — a tox env, a CI job,
#    `uv pip install 'matplotlib==3.10.*'`), record what differs.
pytest                                                        # see what fails
pytest --snapshot-update --snapshot-matplotlib-pin-variant --lf

# 3. Every job, old or new, compares with a plain:
pytest
```

`--lf` is ordinary pytest selection; it just narrows step 2 to the figures
that failed. Commit the variant directories like any other baseline.

What step 2 does, per snapshot: it compares the render against the
**canonical** baseline at the effective tolerance, and writes a variant only
when they differ beyond it. A variant that has become redundant is deleted,
and one that already matches is left untouched, so re-running the command is
a no-op.

A snapshot cannot exist as a variant only: if the canonical baseline is
missing, step 2 fails and tells you to run step 1 first.

### Things to know

- **Pinning happens in the environment, never on the command line.** There is
  no option, environment variable or flag value that names a tag. Installing
  matplotlib 3.10 is what makes a run write to `__snapshots_variants__/mpl-3.10/`.
- **Patch releases share a tag.** `mpl-3.10` covers 3.10.x; matplotlib does
  not normally change rendering in a patch release.
- **One tag at a time**, with no fallback chain — a variant is keyed on the
  matplotlib version and nothing else.
- **Re-baselining canonical can outdate the variants.** Only the environment
  a variant came from can tell, so the plugin warns and leaves them alone;
  those jobs will fail until you re-run step 2 there. The warning is
  collected in the xdist workers and never reaches the controller, so a
  `-n` re-baseline stays silent — one more reason to update without xdist
  (see below). That includes the
  environment you are sitting in: if it owns a variant for the snapshot you
  just re-baselined, that variant still shadows the new canonical image and
  your next plain `pytest` fails until step 2 runs.
- **Deleting a test leaves its variants behind until step 2 runs.** A
  comparison run touches nothing, and `--snapshot-update` removes only the
  orphaned canonical baseline. The next clean step-2 pin run in an environment
  deletes that environment's variants which no canonical baseline backs, and
  lists what it removed; other environments' variants wait for their own pin
  run, or a `git rm`.
- **Variant generation refuses `-n`.** Reading variants is xdist-safe (that
  is what CI does), but a pin run deletes redundant variants and reports
  the deletions, which is per-worker bookkeeping — the flag errors out
  under pytest-xdist.
- **Retiring an environment** is a manual `git rm -r` of its tag directory
  under `__snapshots_variants__/`.

## xdist support

Works with `pytest-xdist` (`-n auto`). Workers write per-worker result
fragments; the controller merges them at session end before generating
reports. Syrupy's own unused-snapshot detection is limited under xdist with
`--snapshot-update`, and the stale-variant warning stays in the workers —
regenerate baselines without xdist when possible.

Fragment merge and report generation read the worker-written files from a
single `figure-report/` directory, so xdist support assumes a **shared (or
local) filesystem** — the common single-host `-n auto` case. Distributed runs
that place workers on separate filesystems (e.g. `--tx ssh=...`) won't surface
their fragments or image artifacts to the controller.

## Custom fixture wrappers

To set test-scoped defaults (e.g. a different tolerance for one package),
wrap the fixture in a `conftest.py` and call `set_defaults()`:

```python
import pytest


@pytest.fixture
def snapshot_matplotlib(snapshot_matplotlib):
    return snapshot_matplotlib.set_defaults(tolerance=5.0)
```

`set_defaults(tolerance=..., savefig_kwargs=..., remove_text=..., auto=...)`
applies to **every** assertion in the test, including the ones made by the
auto path. Calling `snapshot_matplotlib(tolerance=5.0)` in a wrapper fixture
instead would set the tolerance for the *first* assertion only — per-call
overrides are reverted once the assertion they precede has run.
