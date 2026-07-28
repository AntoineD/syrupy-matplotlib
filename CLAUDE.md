# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Testing

```bash
just test [args]                                  # Alias for uv run pytest
just coverage [args]                              # Tests + coverage XML/HTML reports
just test tests/path/to/test_file.py::test_fn     # Run single test
just test tests/ -k "keyword"                     # Run by keyword
```

Pytest config in `pyproject.toml` under `[tool.pytest.ini_options]`.

### Linting and Formatting

```bash
just check          # Format + lint (runs prek install && prek run --all-files)
```

### Type Checking

```bash
just check-typing   # ty
```

### Other

```bash
just install        # uv sync
```

### Coverage and pytester subprocesses

`--runpytest=subprocess` means pytester spawns fresh Python processes that
don't inherit the parent's coverage tracer. `tests/conftest.py::pytest_configure`
sets `COVERAGE_PROCESS_START` when the `pytest-cov` plugin is active; the
`coverage` package's site `.pth` then calls `coverage.process_startup()` in
each subprocess. Without this, coverage drops to ~49% and you get a
`module-not-measured` warning.

### Workflow for iterating on the plugin itself

```bash
just test --snapshot-update   # regenerate PNG baselines
just test                     # compare against baselines
```

## Architecture

`syrupy-matplotlib` is a pytest plugin (`src/syrupy_matplotlib/`) that compares matplotlib figures against stored PNG baselines via `matplotlib.testing.compare.compare_images`.

### Data flow through a single test

1. **`_plugin.py`** — registers the `snapshot_matplotlib` fixture and a `Plugin` singleton; on session start clears the previous session's reports and images from `figure-report/`, on session finish merges xdist result fragments, then either writes reports or prunes empty `figure-report/` subdirs (whichever applies).
2. **`_figures.py`** — `save_figure_to_bytes()` serializes the figure to PNG bytes once.
3. **`_comparison.py`** — `run_comparison()` wraps `matplotlib.testing.compare.compare_images()` and returns an immutable `ImageResult`. Match artifacts are unlinked when no report is requested; the controller prunes empty `figure-report/` subdirs at session end.
4. **`_reporting.py`** — collects `ResultRecord` objects; `_json_report.py` / `_html_report.py` consume them at session end.

### Key modules

| Module | Responsibility |
|---|---|
| `_types.py` | `ImageMatchStatus`, frozen `ImageResult`, `is_passing()` |
| `_config.py` | `Config` frozen dataclass; `resolve_config()` merges CLI + INI |
| `_params.py` | `SnapshotParams` per-assertion; `merge()` applies per-call overrides |
| `_determinism.py` | `deterministic_context()` CM — calls `matplotlib.testing` helpers, manages `SOURCE_DATE_EPOCH` |
| `_figures.py` | `save_figure_to_bytes()` (PNG via in-memory `BytesIO`) |
| `_comparison.py` | `run_comparison()` — writes baseline + actual to disk for `compare_images`, unlinks on match when not kept |
| `_extension.py` | `MplFigureExtension` (syrupy `SingleFileSnapshotExtension`); `serialize`, `matches`, `_record` |
| `_assertion.py` | `MplSnapshotAssertion` — accepts mpl kwargs on `__call__`, stamps state on extension before `matches()` |
| `_fixture.py` | `snapshot_matplotlib` fixture; deterministic context + auto-discover/auto-assert/auto-close of figures |
| `_xdist.py` | Workers save JSON result fragments, controller merges at session end |
| `_plugin.py` | Hook registration, `Plugin` class, terminal summary, report generation, `figure-report/` housekeeping. The entry-point module: pytest imports it at every startup, so it must stay free of matplotlib/syrupy imports — which is why pure helpers live here rather than in a module that would drag those in |
| `_reporting.py` | `ResultRecord`, `RunSummary`, `ResultCollector` (xdist-aware) |

### Storage layout

```text
tests/
    test_foo.py
    __snapshots__/
        test_foo/
            test_bar.png          # baseline image
            test_bar[param].png   # parametrized variant
    __mpl_variants__/             # per-environment baseline variants
        mpl-3.10/
            test_foo/
                test_bar.png
```

Baseline filename stem = test function name + parametrize ID (brackets preserved on Linux).

### Baseline variants

A comparison prefers `__mpl_variants__/<tag>/<module_stem>/<name>.png` over the canonical baseline when it exists; the tag is derived from the installed matplotlib and cannot be overridden. `--snapshot-update --snapshot-matplotlib-pin-variant` writes those files (only where the render differs from the canonical baseline beyond the tolerance), plain `--snapshot-update` writes canonical ones.

Variants are handled *around* syrupy, not through it, and this is load-bearing. Syrupy counts the location `get_location` returns as the snapshot the run used, then reports every other file under `__snapshots__/` as unused — which fails the session — and deletes it while updating. Its default (amber) extension discovers that whole tree, so one plain `snapshot` fixture anywhere in the directory arms the sweep. Hence:

- `get_location` reports the **canonical** path in every mode, so no run can lose a baseline to that sweep;
- `read_snapshot_data_from_location` substitutes the variant's bytes;
- `_decide_variant_write` writes the variant file itself and returns `True` (a `False` return would make syrupy write, at the canonical path, and report every pinned figure as a failure);
- `VARIANT_ROOT_DIRNAME` (`_config.py`) keeps variants out of `__snapshots__/` entirely, since a variant for another environment is unused there by definition;
- `_plugin._prune_orphaned_variants` replaces syrupy's unused-snapshot cleanup for variants, deleting those with no canonical baseline left. It runs only on a clean pin run — a failed one may be failing *because* a canonical baseline went missing.

`MplFigureExtension.discover_snapshots` drops anything below the module directory, which is where variants used to live.

### Comparison

Pixel comparison via `matplotlib.testing.compare.compare_images` with RMS tolerance. RMS threshold comes from `snapshot_matplotlib_tolerance` INI (default `0`, matching `matplotlib.testing`) or per-call `snapshot_matplotlib(tolerance=...)`.

### Tests

`--runpytest=subprocess` is set in `pyproject.toml` so pytester integration tests run in a subprocess (required — in-process mode causes numpy re-import errors under Python 3.14). The `pytester` fixture is enabled via `pytest_plugins = ["pytester"]` in `tests/conftest.py`.

### Python conventions

- `@dataclass(frozen=True, slots=True)` for all result types
- docstring format is google, mkdocs compatible
- declare class attributes with type and docstring in class body
- `__init__` arguments doc are in its docstring
- no sphinx-style directives (`:param:`, `:returns:`, `:raises:`) in docstrings
- put imports at top of modules, unless necessary
- method and function names start with a verb (e.g. `compute_summary`, `record`, not `summary`, `result`)
