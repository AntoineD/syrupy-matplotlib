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

1. **`_plugin.py`** — registers the `snapshot_matplotlib` fixture and a `Plugin` singleton; on session finish merges xdist result fragments, then either writes reports or prunes empty `figure-report/` subdirs (whichever applies).
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
| `_plugin.py` | Thin orchestration: hook registration, `Plugin` class, terminal summary, report generation |
| `_reporting.py` | `ResultRecord`, `RunSummary`, `ResultCollector` (xdist-aware) |

### Storage layout

```text
tests/
    test_foo.py
    __snapshots__/
        test_foo/
            test_bar.png          # baseline image
            test_bar[param].png   # parametrized variant
```

Baseline filename stem = test function name + parametrize ID (brackets preserved on Linux).

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
