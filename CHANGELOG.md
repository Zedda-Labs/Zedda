# Changelog

All notable changes to Zedda will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- Only 4 of 7 C++ test binaries were running in CI — switched to CMake-driven builds for all 6 assertion-based test binaries (C-06)
- `.gitignore` contained duplicate content (W-DX-06)

## [0.2.0] - 2026-06-28

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
