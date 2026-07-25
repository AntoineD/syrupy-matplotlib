# Changelog

All notable changes of this project will be documented here.

The format is based on [Keep a
Changelog](https://keepachangelog.com/en/1.0.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- A baseline with different pixel dimensions (a figsize or dpi change) now
  fails as a normal comparison with a clear message, and is counted in the
  terminal summary and reports. Previously matplotlib's
  `ImageComparisonFailure` escaped as a raw traceback and the comparison
  left no record anywhere.

- HTML reports now escape markup in test ids and error messages. Escaping
  was silently off (`select_autoescape` matches template-name suffixes and
  the templates end in `.jinja2`), so a routine parametrize id like
  `test_plot[<lambda>]` parsed as an HTML tag and vanished from the report.

- The auto-assert path can no longer silently skip a figure. Asserted
  figures were tracked by `id()`, so a new figure allocated at a closed,
  already-asserted figure's address was treated as asserted; tracking is
  now by object liveness.

- Update mode no longer reports a baseline as "created" when serializing
  the figure fails (e.g. rejected `savefig_kwargs`).

- Orphaned xdist result fragments left in `figure-report/` by a crashed
  run are now cleaned up at the start of the next session instead of
  accumulating forever.

- Disabling syrupy (`-p no:syrupy`) now produces a one-line usage error
  saying the plugin requires it, instead of an `INTERNALERROR`
  `AttributeError` traceback.

- Session state stamped on the extension class is cleared at
  `pytest_unconfigure`, so repeated in-process pytest runs (e.g.
  `pytest.main()` called twice) no longer read the previous session's
  collector.

- A whitespace-only `snapshot_matplotlib_auto` is treated as unset instead of
  raising. Only reachable from `pyproject.toml`, which preserves whitespace
  where `.ini` sources strip it.

- Malformed `--snapshot-matplotlib-*` flags and `snapshot_matplotlib_*` INI
  values now report as a pytest usage error rather than an `INTERNALERROR`
  traceback.

- `savefig_kwargs` setting `format` is rejected with a message naming the
  option at fault, instead of colliding inside `Figure.savefig()` with
  `TypeError: got multiple values for keyword argument 'format'`.

- Support matplotlib 3.11. Its `set_font_settings_for_testing()` now sets
  `text.hinting = "default"` (was `"none"`) and no longer sets
  `text.hinting_factor`, which broke the determinism tests. Those tests now
  derive the expected rcParams by running the helper instead of hardcoding
  its values, so they track matplotlib's choices across releases.

### Changed

- Pytest startup no longer pays for matplotlib. The plugin entry point
  imported matplotlib and syrupy eagerly (~400 ms warm) on every pytest
  run in an env with the plugin installed, figure tests or not; the heavy
  modules now load on the first use of the `snapshot_matplotlib` fixture,
  dropping entry-point import to ~3 ms.

- Report mode no longer decodes byte-identical images. Every passing test
  under `--snapshot-matplotlib-report` went through `compare_images`
  (~8 ms of PNG decoding per comparison) even when the rendered bytes
  matched the baseline exactly; identical bytes now short-circuit to a
  MATCH while still writing the report artifacts.

- JSON report summaries now satisfy `total == passed + failed`. Records
  carried an optional `image_status` that three call sites classified
  differently, so an unclassified record could be counted in `total` alone
  while the terminal summary reported it as failed. The field is now
  required — every record describes a comparison that ran.

- Declared minimum pytest is now 8 (was 7), matching the floor `syrupy>=5.1`
  already forces transitively. No resolution changes — pytest 7 was never
  installable alongside this plugin.

- Minimum supported matplotlib is now 3.5 (was 3.4). 3.5 is the first release
  with cp310 wheels, so the old floor was uninstallable on this project's own
  minimum Python without a C++ toolchain — `just test-min-deps` could never
  run. No API used by the plugin changed between the two.

- **Baselines with visible text, generated under matplotlib ≤ 3.10, will not
  match under matplotlib ≥ 3.11.** The hinting change above alters glyph
  rasterization. Regenerate with `--snapshot-update`, or insulate the suite
  with `remove_text = true` or a non-zero `snapshot_matplotlib_tolerance`.

## [0.1.1] - 2026-05-10

### Fixed

- Preserve font hinting through style reset. `plt.style.context(style,
  after_reset=True)` resets rcParams to matplotlib defaults, undoing
  `set_font_settings_for_testing()` (`text.hinting`, `text.hinting_factor`,
  `font.family`). The previous one-shot guard meant the helpers ran once
  per process and could not re-apply after the reset, so text glyphs
  rendered with `force_autohint` instead of `none` and PNGs were not
  reproducible against baselines generated by
  `matplotlib.testing.decorators.image_comparison`. The testing helpers
  now fire every test, and the fixture enters `plt.style.context` before
  `deterministic_context` so font settings persist into the test body.

## [0.1.0] - 2026-05-09

Initial release.
