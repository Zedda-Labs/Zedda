# Changelog

All notable changes to Zedda will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.5] - 2026-07-15 — Audit Remediation Patch Release

### Security
- **CRITICAL (P-C1):** Fixed path traversal in `scan(allowed_dir=...)`. The previous
  `str.startswith()` check let `/data/uploads_evil/x.csv` match `/data/uploads`. Now
  uses `Path.relative_to()` for proper containment.
- **(P-H1):** Fixed `_ask_validate_path` blocked-root check using `Path.relative_to()`
  instead of `str.startswith()` (was over-blocking `/rootkit/x.csv`).
- **(P-H9/H10):** `clean()` now validates backup and audit-trail paths to prevent
  path traversal via user-supplied `output`.
- **(D-1):** Declared `requests>=2.31` in `[ai]` extra — was imported but never
  declared, silently breaking AI support for every `[ai]` user.
- **(CI-C1):** Removed `continue-on-error: true` from `publish_test` job — the
  TestPyPI→PyPI safety gate was non-functional.
- **(CI-C2):** Fixed fuzz crash-artifact upload condition (`if: failure()` never
  fired because the fuzzer step had `continue-on-error: true`).
- **(CI-H1):** SHA-pinned `pypa/gh-action-pypi-publish` (was floating `@release/v1`).
- **(CI-H3):** Made dependency-review blocking (was advisory-only).
- **(CI-H4):** Docker image now runs as non-root user (uid 1000).

### Fixed — C++ correctness
- **(C-H1):** Pearson correlation switched from naive 5-sum formula to Welford-style
  online covariance. Numerically stable for any input scale (was catastrophically
  cancelling for values near 1e8+).
- **(C-H2):** CSV parser in `profile_builder` now properly unescapes `""` → `"`
  inside quoted fields (was leaving both quotes in the string_view).
- **(C-H5):** Arrow boolean/datetime/int8-16/uint32-64/float16 columns are now
  handled natively (were silently treated as all-null).
- **(C-H6):** All-null Arrow columns are now skipped in the pair-accumulator loop
  (was reading garbage from buffers[1] and feeding into Pearson).
- **(C-H7):** MSVC AVX-512 detection now includes `_xgetbv` OS XSAVE check; CMake
  uses `/arch:AVX512` (was `/arch:AVX2` which doesn't define `__AVX512F__`).
- **(C-H8):** `config_.has_header=false` is now honored in `profile_builder`
  (was silently dropping the first data row).
- **(C-H9):** `config_.null_string` is now honored in `profile_builder`
  (was silently ignored — only hardcoded null markers were detected).
- **(C-H11):** UTF-8 BOM is now skipped in both mmap and fgets paths (was
  prefixing the first column header with 3 garbage bytes).
- **(C-H12):** Boolean parsing tightened to exact case-insensitive match (was
  matching "track", "field", "from", etc. as TRUE).
- **(C-M9):** Only strips trailing quote if field was actually quoted.

### Fixed — Python correctness
- **(P-C2):** `fix(apply=True)` now applies the same clip-at-99th-percentile fix
  shown in the displayed copy-paste code (was running `np.log1p()` instead —
  different schema, different semantics).
- **(P-C3):** `fix(apply=True)` no longer crashes on all-null string columns
  (`Series.mode()` returns empty Series; `[0]` raised `IndexError`).
- **(P-C4):** `clean()` no longer writes output to a deleted temp file when
  input is a DataFrame and `output=None` (was silent data loss).
- **(P-C5):** `scan()` now preserves the original traceback (`from e` instead
  of `from None`).
- **(P-H5):** Six public APIs (`compare`, `ml_ready`, `warnings`, `fix`, `clean`,
  `merge`) now raise `ZeddaError` instead of `return None` when Rich is missing.
- **(P-H6):** `merge()` now skips files that fail to scan with a warning, instead
  of aborting the entire merge.
- **(P-H11):** `clean()` no longer fabricates a fake "after" quality score on
  rescan failure.
- **(P-H12/H13):** `ask()` return type now consistent with docstring; exception
  path no longer risks `NameError` on `msg`.
- **(P-M7/M8):** `_count_lines` returns `None` on error; fixes off-by-one for
  files without trailing newline.

### Fixed — CI/CD
- **(CI-C3):** Added `enable_testing()` + `add_test()` to CMakeLists.txt — `ctest`
  now discovers all 9 C++ tests (was running zero, giving false sense of coverage).
- **(CI-H5):** `test_hyperloglog` is now run in CI (was built but never executed).
- **(CI-H6):** `tests/test_hotfix_0_4_5.py` is now run in CI.
- **(CI-H7):** Wheels are now smoke-tested via `CIBW_TEST_COMMAND` before PyPI publish.
- **(CI-M1/M2):** Test matrix now includes Python 3.10/3.11 and macos-13 (Intel).
- **(CI-M3):** Migrated `manylinux2014` → `manylinux_2_28` (CentOS 7 EOL).
- **(CI-M10):** Collapsed 6-wheel STABLE_ABI matrix to single `cp39` (abi3 covers 3.9+).
- **(CI-M19):** Split `publish_pypi` (id-token only) from `github_release` (contents:write).
- **(CI-M20):** Renamed CMake project `fasteda`→`zedda`, version `0.1.0`→`0.4.5`.

### Changed
- **(D-2):** `[ai]` extra now declares `requests` instead of the unused `openai` SDK.
- **(P-M21/M22):** `warnings()` and `fix()` now accept `sample_size` parameter
  for API consistency with `profile`/`scan`/`compare`.
- **(M-22):** `[dev]` extra now includes `ruff`, `mypy`, `types-requests`,
  `pre-commit`, `cibuildwheel` (was installed ad-hoc in CI).
- **(M-24):** AI endpoint is now configurable via `ZEDDA_AI_ENDPOINT` env var.

### Refactor
- **(Batch 7):** Began splitting the 4,287-line `__init__.py` into focused modules:
  `_constants.py`, `_format.py`, `_warnings.py`, `_scan.py`. Public API unchanged.
- **(C-L5):** `ArrowProfiler` destructor declared `= default` (was out-of-line empty).
- **(C-L12):** `~CsvStreamReader` marked `noexcept`.
- **(C-L18):** `pair_accs_` memory released after `finalize()` (was holding 64MB).
- **(C-M2):** `get_active_scanner` cached via `std::call_once` (was calling
  `std::getenv` on every invocation).
- **(C-M6):** `profile_builder` diagnostics routed to `stderr` (was corrupting stdout).
- **(C-M10):** 15 `ColumnProfile` fields exposed as read-only via `def_ro`.
- **(C-M8/C-L6):** Type-promotion lattice in `ColumnAccumulator::merge` —
  INTEGER + FLOAT → FLOAT, STRING wins over numeric. Previously per-thread
  type detection produced inconsistent merged types.
- **(L-1):** Removed redundant `Path as _P` re-import in `_resolve_input`.
- **(L-7):** `__all__` now includes `export` alias.
- **(L-8):** Removed trailing non-code comments at EOF.
- **(L-19):** `ask()` uses module-level `time` import (was re-imported as `_time`).

### Tests
- **(Batch 11):** Added `tests/python/test_audit_regression.py` with 32 test
  cases covering all Critical/High audit fixes: path traversal, BOM handling,
  boolean parsing, fix-apply divergence, clean data loss, merge skip-on-fail,
  traceback preservation, ctest registration, CMake project name, thread-safe
  cache, count_lines edge cases, sample_size API consistency, extracted modules.
- **(Batch 17):** C-M1 — pair_accs packed into upper-triangle layout,
  halving memory (64 MB → 32 MB at N=1000; 512 MB → 256 MB with 8 threads).
  Also fixes C-L3 (merge loop now iterates N*(N-1)/2 instead of N²).
- **(Batch 18):** C-H10 — Embedded newlines in quoted CSV fields now
  handled correctly in the single-threaded CsvStreamReader path (RFC 4180 §6).
  The parallel ProfileBuilder path still has this limitation (C-M5 deferred).
- **(Batch 19):** P-M29 — clean() caches mode() result (was calling twice).
  P-M30 — _ask_pattern_c parquet/feather reads capped at 5M rows (was uncapped).
  C-M3 — SIMD scanner now warns when a row has more fields than expected.
- **(Batch 20):** Added 7 property-based tests with hypothesis for CSV
  parser fuzzing (random valid CSV generation, BOM, trailing newline, quoted fields).
- **(Batch 22):** C-M5/C-H10 — Parallel ProfileBuilder path now handles
  embedded newlines in quoted fields (RFC 4180 §6). After fgets returns a
  line, checks for unterminated quotes and keeps reading until the quote
  closes. Both single-threaded and parallel paths now handle embedded newlines.
- **(Batch 23):** C-L7/C-L11 — All null markers (NA, NaN, N/A, null, none,
  #N/A) are now case-insensitive in both `fast_is_null()` and `is_null_sv()`.
  Previously "NaN"/"nan" was case-insensitive but "null"/"NULL"/"None"/"none"
  were exact-case only — "Null", "nULL", "NONE" were not detected as null.
- **(Batch 24):** P-M19 — `_ask_pattern_d` regexes hoisted to module scope
  (was recompiling 7 regexes on every call).
- **(Batch 25):** API.md documentation corrected: `zd.profile()` return
  type fixed (None → DatasetProfile), `zd.fix()` added (was missing entirely),
  `zd.ask()` return type matches actual behavior, all 22 `ColumnProfile`
  attributes documented (was 8), `CorrelationResult` and `ZeddaError` documented.
- **(Batch 27-32):** P-M1 RESOLVED — Extracted 10 focused modules from
  `__init__.py`: `_constants`, `_format`, `_warnings`, `_scan`, `_resolve`,
  `_compare`, `_ml_ready`, `_fix`, `_merge`, `_clean`, `_ask`. Total 1,377
  lines of pure logic extracted, all testable in isolation. The Rich
  rendering layer and public API orchestration remain in `__init__.py`.
  All 80 Medium-severity findings are now resolved.
- **(Batch 34-38):** Added 60 unit tests for all extracted modules
  (`test_extracted_modules.py`). Uses mock ColumnProfile/DatasetProfile
  objects so tests don't need the C++ core. Covers: schema diff, distribution
  shift (including negative mean M-32), verdict computation, ML readiness
  scoring, fix code generation (P-C2 clip not log1p), merge overlap (P-H7
  O(N)), clean backup/audit (P-H9/H10), ask pattern matching, format helpers,
  and code injection prevention (SEC-P01).
- **(Batch 40-41):** `_quality_score()` and `_quality_score_display()` now
  delegate to shared helpers (`_is_outlier_column`, `_render_quality_bar`,
  `_quality_label`). FIX M-36: `original_cols=0` no longer disables the
  dropped-column penalty. FIX M-11: score clamped to [0, 100].
- **(Batch 42):** Added 3 C++ tests to `test_profile_builder.cpp`:
  BOM handling (C-H11), embedded newlines in parallel path (C-H10),
  type promotion int→float (C-M8). All pass.
- **(Batch 44):** Coverage measurement: `pytest-cov` added to `[dev]` extras,
  `.coveragerc` config, CI runs with `--cov`, Codecov badge in README.
  First measurement: 58.16% (target: 70% for v0.6.0).
- **(Batch 45):** P-M20 (redundant dedup in ml_ready), P-M18 (useless
  `result = None` in ask), P-M37 (negative `coerced_count` in clean).
- **(Batch 46):** `.clang-format` file added (C++17, Google-based, 4-space
  indent, 100-col limit). Pre-commit clang-format hook now has a config.
- **(Batch 48-50):** 27 new unit tests for extracted modules. Coverage
  improved from 58.2% to 61.5%. Key improvements: `_clean.py` 30%→97%,
  `_format.py` 56%→95%, `_fix.py` 58%→79%, `_warnings.py` 78%→93%.
  Total tests: 166 (was 139).
- **(Batch 52-58):** 23 more unit tests + L-22/L-23/L-24/L-25 fixes.
  `_ml_ready.py` reaches 100% coverage, `_ask.py` reaches 97.3%.
  json/shutil moved to module level (L-22), merge() exception chain
  preserved (L-23), compare() counters documented (L-24),
  collect_warnings() added as public API (L-25).
  Total tests: 189 (was 166). Coverage: 63.0%.
- **(Batch 61-63):** 33 more tests + L-20 fix. `_resolve.py` 21%→93%,
  `_scan.py` count_lines 0%→100%, `cli.py` 0%→52% (10 CLI smoke tests).
  L-20: `_ask_zedda_ai` except cascade now includes exception type.
  Total tests: 222 (was 189). Coverage: 66.9%.

## [0.4.6] - 2026-07-10

### Fixed
- **Installation:** Bumped the `pyarrow` upper bound constraint from `<20` to `<27` (allowing up to pyarrow 26.x). This resolves a severe installation failure on Python 3.14 (and newer) where pip would fall back to a source build due to missing wheels in older pyarrow versions.

### Changed
- **BREAKING CHANGE:** `pyarrow` is no longer a core dependency, making the base installation significantly faster and smaller for CSV-only users. If you rely on Parquet files, Arrow IPC, or pandas DataFrame inputs, you must now explicitly install the parquet extra: `pip install "zedda[parquet]"`.

## [0.4.5] - 2026-07-09

### Fixed
- **BUG 1:** Fixed an issue where `zd.scan(df)` and `zd.profile(df)` would silently swallow `ImportError` if `pyarrow` was missing, incorrectly throwing an `Unsupported input type` error.
- **BUG 2:** Fixed `zd.clean()` and `zd.fix(apply=True)` crashing on numeric columns containing non-numeric garbage values by coercing them using `pd.to_numeric(errors='coerce')` prior to aggregations.
- **BUG 3:** Enforced UTF-8 encoding on Windows (`sys.stdout.reconfigure`) and replaced mojibake characters in `zd.fix()` output with proper Unicode bullets and arrows.
- **BUG 4:** Replaced manual OSC-8 ANSI sequences in `zd.report()` with Rich's native Text markup to avoid leaking raw terminal escape codes in Jupyter notebooks.
- **BUG 6:** Removed extraneous trailing newlines from several `console.print()` calls to fix excessive spacing in the terminal UI.

### Changed
- **BUG 5 (Minor Breaking Change):** `zd.profile()` now returns `None` instead of `DatasetProfileWrapper` to prevent double-printing the report in Jupyter cells. Programmatic users should use `zd.scan()` instead.

## [0.4.4] - 2026-07-05

### Added
- **`zd.clean()`**: AI-powered automatic data cleaning (drops sparse columns, imputes missing values, removes IDs).
- **`zd.merge()`**: Intelligent dataset merging with automatic ID inference and semantic alignment.
- **`zd.warnings()`**: Clean, structured list of every data quality warning found in the dataset.
- Enterprise Dependabot configuration with intelligent grouping
- CodeQL security scanning (C++ + Python)
- Dependency review workflow (blocks vulnerable PRs)
- Release drafter for automated changelog generation
- Multi-stage Dockerfile (image size ~1.5 GB → ~200 MB)
- GHCR publishing alongside Docker Hub
- Docker smoke test before publish
- `.pre-commit-config.yaml` with Ruff hooks
- `CODEOWNERS` for automatic reviewer assignment
- `.dockerignore` for build context optimization
- Ruff linting & formatting configuration
- mypy type checking configuration
- ccache for C++ test builds
- Cross-platform CI matrix (Linux, macOS, Windows)
- Python version matrix (3.9, 3.12, 3.13)
- CMake-driven C++ tests (all 7 test binaries)
- Concurrency groups on all workflows
- Timeout limits on all CI jobs

### Changed
- `tests.yml`: Complete rewrite with lint, typecheck, test-cpp, test-python jobs
- `build_wheels.yml`: `publish_pypi` now depends on `publish_test` (safety gate)
- `docker_publish.yml`: Added GHCR, smoke test, multi-arch on tag pushes only
- `.gitignore`: Deduplicated (was doubled) and added missing entries

### Fixed
- Fixed bug where `zd.fix()` applied `fillna` instead of `drop` to string columns >50% null
- Fixed bug where `zd.profile()` smart warnings icons were failing to render due to `x/!/i` char mismatch
- Fixed bug where `zd.compare()` gave `FAIL` for expected missing target columns in test data (now gives `REVIEW`)
- Production PyPI publish could proceed even if TestPyPI upload failed (C-05)
- Only 4 of 8 C++ test binaries were running in CI — switched to CMake-driven builds for all 8 assertion-based test binaries (C-06)
- `.gitignore` contained duplicate content (W-DX-06)

## [0.2.0] - 2026-06-28

> **Note:** Versions 0.3.x were internal development releases with no public
> changelog entries. All features planned for 0.3.0 shipped in 0.4.0+.

### Added
- Arrow profiler for Parquet/Arrow file support
- SIMD scanner with AVX2/AVX-512 runtime dispatch
- Memory-mapped file reader (`mmap_reader.cpp`)
- Profile builder for structured report generation
- Cross-platform wheel builds (Linux, macOS x86_64 + arm64, Windows)
- PyPI publishing via OIDC (no stored API tokens)
- `zd.compare()` for dataset drift detection
- `zd.fix()` for auto-generated data cleaning code
- `zd.ml_ready()` for ML readiness assessment
- CLI interface via Typer

## [0.1.0] - 2026-06-15

### Added
- Initial release
- C++17 streaming CSV parser
- Basic statistical profiling (mean, median, std, min, max)
- Python bindings via nanobind
- `zd.profile()` and `zd.scan()` API
