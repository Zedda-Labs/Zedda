# Changelog

All notable changes to Zedda will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
- Production PyPI publish could proceed even if TestPyPI upload failed (C-05)
- Only 4 of 7 C++ test binaries were running in CI (C-06)
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
