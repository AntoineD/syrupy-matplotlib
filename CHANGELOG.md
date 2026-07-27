# Changelog

All notable changes of this project will be documented here.

The format is based on [Keep a
Changelog](https://keepachangelog.com/en/1.0.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Baseline variants: a snapshot can carry an extra baseline under
  `__snapshots__/<module>/mpl-<major>.<minor>/`, used instead of the
  canonical one when the run happens under that matplotlib. A CI matrix
  whose oldest Python resolves an older matplotlib no longer fails every
  comparison over rendering differences it cannot avoid — and no job needs
  a special pytest command, since the directory name is derived from the
  installed matplotlib rather than configured.

  `--snapshot-update --snapshot-matplotlib-pin-variant` records them, in
  the environment whose pixels they describe. It writes a variant only
  where the render differs from the canonical baseline beyond the
  tolerance, deletes ones that have become redundant, and refuses to create
  a snapshot that has no canonical baseline yet. It also refuses to run
  under pytest-xdist (`-n`); comparison runs remain xdist-safe. Plain
  `--snapshot-update` keeps writing canonical baselines and warns when it
  rewrote baselines that existing variants may no longer match.

- The JSON report records which baseline each comparison used
  (`baseline_variant`), the HTML reports label it, and the terminal summary
  names the variants a run read. Report format version is now 3.

## [0.2.0] - 2026-07-26

### Added

- `--snapshot-matplotlib-report-dir` and `snapshot_matplotlib_report_dir`
  move the artifact directory, which was hardcoded to `figure-report/` under
  the rootdir. Two invocations sharing one config file (`tox -p`, two CI jobs
  on one checkout) wrote the same artifact paths for the same test and raced
  on them — the fragment sweep below covered the xdist result fragments but
  not the images and reports. The flag wins over the INI option; relative
  values resolve against the rootdir. The rootdir itself is rejected — see
  the clearing behavior below.

- `snapshot_matplotlib_style` composes a comma-separated list, applied left
  to right the way `plt.style.use()` does. The README pointed at matplotlib's
  own `("classic", "_classic_test_patch")` pairing, but writing it handed the
  raw string to `plt.style.context()`, which raised a bare `OSError` during
  fixture setup and errored out every test in the suite. `Config.style` and
  `SnapshotParams.style` are tuples now, not strings.

- `snapshot_matplotlib.set_defaults(tolerance=..., savefig_kwargs=...,
  remove_text=..., auto=...)` sets defaults for every assertion in the test.
  The wrapper-fixture recipe in the README returned
  `snapshot_matplotlib(tolerance=...)`, whose overrides syrupy reverts after
  the next assertion — so a wrapper meant to loosen a whole package loosened
  one assertion per test and left the rest at the INI default.

### Fixed

- An auto-asserted figure whose serialization *raised* now reports the real
  error. Syrupy's `_assert` catches every exception and returns `False`, so a
  rejected `savefig_kwargs` reached the auto path indistinguishable from a
  pixel mismatch and was reported as "figure mismatch" — blaming the figure
  for a config error and sending the user after a diff that was never
  computed. The explicit `assert fig == snapshot_matplotlib` path already
  surfaced the traceback.

- The report directory now describes the run that just finished. Only empty
  subdirectories were pruned, so a failing run's `report.html` and its
  actual/baseline/diff PNGs survived a later green run, still listing
  failures that were fixed; a CI job archiving the directory out of a cached
  workspace published a report contradicting its own run. Reports and `*.png`
  artifacts are cleared at session start, on the controller only. Result
  fragments keep their age gate, where deleting a live session's file would
  lose results for good.

- A missing baseline now writes the rendered figure to `figure-report/` and
  links it from the report, as documented. Syrupy skips the extension's
  `matches()` when there is no baseline, so the record carried no image at
  all and the auto-emitted failure report showed an imageless card.

- A test that requests the fixture with auto enabled and compares no figure
  now warns instead of passing silently. Auto-discovery only sees
  pyplot-managed figures, so a bare `Figure()` left the test green with
  nothing compared. Suites running under `-W error` will see such a test
  fail — assert the figure explicitly, or pass `auto=False` when a test
  deliberately compares nothing.

- A blank or whitespace-only INI value is treated as unset for every
  `snapshot_matplotlib_*` option, falling back to the default.
  `snapshot_matplotlib_remove_text =` used to abort the run with "Expected
  true/false", and a blank style or backend reached matplotlib as the empty
  string. (Whitespace-only values survive only in `pyproject.toml`, which
  preserves whitespace where `.ini` sources strip it.)

- Orphaned xdist result fragments left in `figure-report/` by a crashed run
  are cleaned up at the start of the next session instead of accumulating
  forever — but only fragments older than an hour, so two sessions sharing
  a rootdir (`tox -p`, two CI jobs on one checkout) cannot silently drop
  each other's unmerged worker results from the report.

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

- Disabling syrupy (`-p no:syrupy`) now produces a one-line usage error
  saying the plugin requires it, instead of an `INTERNALERROR`
  `AttributeError` traceback.

- Session state stamped on the extension class is cleared at
  `pytest_unconfigure`, so repeated in-process pytest runs (e.g.
  `pytest.main()` called twice) no longer read the previous session's
  collector.

- Malformed `--snapshot-matplotlib-*` flags and `snapshot_matplotlib_*` INI
  values now report as a pytest usage error rather than an `INTERNALERROR`
  traceback.

- `savefig_kwargs` setting `format` is rejected with a message naming the
  option at fault, instead of colliding inside `Figure.savefig()` with
  `TypeError: got multiple values for keyword argument 'format'`.

- Support matplotlib 3.11, whose `set_font_settings_for_testing()` sets
  `text.hinting = "default"` (was `"none"`) and no longer sets
  `text.hinting_factor`. See the baseline-regeneration note below.

- The report directory may not resolve to the rootpath **or any of its
  ancestors**. The old guard compared the unresolved path to the rootpath
  alone, so `--snapshot-matplotlib-report-dir=..` passed — and the
  session-start sweep then deleted every `*.png` under the rootpath's
  parent, the project's own `__snapshots__/` baselines included.

- A truncated xdist result fragment no longer aborts the session-end merge.
  Fragments are written to a temp name and renamed into place, and the
  controller discards an unparsable fragment with a warning. A worker killed
  mid-write (OOM, timeout) previously fed broken JSON into the merge, and
  the resulting `INTERNALERROR` lost every worker's summary and reports
  instead of one worker's records.

- The warning about `--snapshot-ignore-file-extensions=png` reaches pytest's
  warnings summary. It was raised before pytest installs its warning
  capture, so it bypassed the summary and only surfaced on stderr when the
  user's filters happened to allow it.

- Auto-discovery can no longer lose a figure to number reuse. matplotlib
  numbers a new figure `max(live numbers) + 1`, so a test that closed a
  pre-existing figure handed its number to the next figure it opened — which
  the number-based baseline set then treated as pre-existing: no
  auto-assert, no auto-close, test green with nothing compared. Pre-existing
  figures are tracked by object liveness now, as the asserted set already
  was.

- `--collect-only` no longer wipes the previous run's failure report and
  comparison artifacts. A collection pass runs no comparison and writes
  nothing, so the session-start clearing destroyed exactly the diagnostics
  the user was reading.

- Image URLs in the HTML report are percent-encoded, so a `#` or `?` in a
  parametrize id no longer truncates the link and breaks the image card.

- A negative `snapshot_matplotlib_tolerance` — or per-call
  `snapshot_matplotlib(tolerance=...)` — is rejected up front. It silently
  failed every comparison, byte-identical images included, with nothing
  pointing at the setting.

- `dir(syrupy_matplotlib)` advertises the lazy public exports; PEP 562's
  `__getattr__` needs the matching `__dir__` for completion and doc tooling
  to see them.

### Changed

- Documented the real option precedence. "CLI flags override INI options"
  described a layering that did not exist — `--snapshot-matplotlib-report`
  had no INI counterpart and no INI option had a CLI one.

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
