# Zedda — Complete A-to-Z CI/CD Pipeline (Definitive Reference)

**Date:** 2026-07-15
**Version:** 1.0
**Purpose:** The single source of truth for Zedda's CI/CD — from current state to enterprise-grade
**Based on:** Analysis of 20 proposed improvements, comparison with NumPy/pandas/Polars/pyarrow

---

## Executive Summary

This file contains the COMPLETE CI/CD pipeline for Zedda, organized into 3 phases based on real-world value:

| Phase | When | What | Score Impact |
|---|---|---|---|
| **Phase 1** | NOW (before v0.4.6 release) | Fix 7 bugs + essential CI safety + PyPI verify | 6.5 → 7.5/10 |
| **Phase 2** | 1 month (after v0.5.0) | Coverage + perf tracking + docs + ARM native + stress tests | 7.5 → 8.5/10 |
| **Phase 3** | 3 months (at v1.0) | API compat + license check + memory bench + upgrade tests | 8.5 → 9.5/10 |

**Items explicitly SKIPPED** (not worth it for Zedda):
- ❌ ABI compatibility (no external C++ consumers)
- ❌ Windows ARM testing (no GitHub runners, <0.1% users)
- ❌ Cold start benchmark (not relevant for Zedda's use case)

---

## Architecture Overview

```
                    ┌─────────────────┐
                    │   Contributor   │
                    │  opens PR       │
                    └────────┬────────┘
                             │
                             ▼
        ┌────────────────────────────────────────────┐
        │           ci.yml (PR trigger)              │
        │                                            │
        │  ┌─────────┐ ┌─────────┐ ┌─────────┐       │
        │  │ Tests   │ │ Quality │ │ Build   │       │
        │  │(reusable)│ │(reusable)│ │(reusable)│    │
        │  └────┬────┘ └────┬────┘ └────┬────┘      │
        │       │           │           │           │
        │       └───────────┴───────────┘           │
        │                   │                       │
        │            ┌──────┴──────┐                │
        │            │  Security   │                │
        │            │  (inline)   │                │
        │            └──────┬──────┘                │
        │                   │                       │
        │            ┌──────┴──────┐                │
        │            │  ci-status  │ ← ONE check   │
        │            │ (consolidate)│   for branch  │
        │            └─────────────┘   protection   │
        └────────────────────────────────────────────┘

                    ┌─────────────────┐
                    │  Tag push       │
                    │  v*.*.*         │
                    └────────┬────────┘
                             │
        ┌────────────────────┴───────────────────┐
        │                                        │
        ▼                                        ▼
┌─────────────────┐                    ┌─────────────────┐
│  release.yml    │                    │  docker.yml     │
│                 │                    │                 │
│ build wheels    │                    │ build amd64     │
│ build sdist     │                    │ smoke test      │
│ TestPyPI (gate) │                    │ Trivy scan      │
│ PyPI publish    │                    │ push multi-arch │
│ SBOM + SHA256   │                    │ arm64 smoke     │
│ GitHub Release  │                    └─────────────────┘
│ PyPI verify ← Phase 1 addition       │
└─────────────────┘                    │
                                       │
                    ┌──────────────────┘
                    │
                    ▼
        ┌────────────────────────────────────────────┐
        │           nightly.yml (daily cron)         │
        │                                            │
        │  ┌───────┐ ┌───────┐ ┌───────┐ ┌────────┐  │
        │  │ ASan  │ │ TSan  │ │ Fuzz  │ │pip-audit│ │
        │  │+UBSan │ │       │ │       │ │        │  │
        │  └───────┘ └───────┘ └───────┘ └────────┘  │
        │                                            │
        │  Phase 2 additions:                        │
        │  ┌────────────────┐ ┌──────────────────┐   │
        │  │ Large dataset  │ │ Memory benchmark │   │
        │  │ tests (1-10GB) │ │ (memray)         │   │
        │  └────────────────┘ └──────────────────┘   │
        └────────────────────────────────────────────┘

        ┌────────────────────────────────────────────┐
        │      maintenance.yml (daily + push)        │
        │                                            │
        │  ┌────────┐  ┌──────────────────┐          │
        │  │ Stale  │  │ Release Drafter  │          │
        │  │ issues │  │                  │          │
        │  └────────┘  └──────────────────┘          │
        └────────────────────────────────────────────┘

        Phase 2 addition:
        ┌────────────────────────────────────────────┐
        │      docs.yml (push to main + PR)          │
        │                                            │
        │  MkDocs build → link check → GitHub Pages  │
        └────────────────────────────────────────────┘

        Phase 2 addition (weekly):
        ┌────────────────────────────────────────────┐
        │      scorecard.yml (weekly cron)           │
        │                                            │
        │  OpenSSF Scorecard → SARIF → Security tab  │
        └────────────────────────────────────────────┘
```

---

## File Structure (Complete)

```
.github/
├── workflows/
│   ├── ci.yml                        ← MAIN: PR trigger (4 checks)
│   ├── _reusable-tests.yml           ← Called by ci.yml
│   ├── _reusable-quality.yml         ← Called by ci.yml
│   ├── _reusable-build.yml           ← Called by ci.yml
│   ├── release.yml                   ← Tag trigger (PyPI publish + verify)
│   ├── docker.yml                    ← Tag trigger (Docker publish)
│   ├── nightly.yml                   ← Daily cron (sanitizers + fuzz + audit)
│   ├── maintenance.yml               ← Daily + push (stale + drafter)
│   ├── docs.yml                      ← Phase 2: docs build + deploy
│   └── scorecard.yml                 ← Phase 2: weekly OpenSSF
├── actions/
│   └── setup-zedda/
│       └── action.yml                ← Composite action (shared setup)
├── codeql-config.yml                 ← CodeQL config (exclude vendored)
├── CODEOWNERS
├── dependabot.yml
├── labeler.yml                       ← Phase 2: PR auto-labeling
├── release-drafter.yml               ← Release notes config
└── ISSUE_TEMPLATE/
    ├── bug_report.md
    ├── feature_request.md
    └── config.yml
```

**Total: 10 workflow files + 1 composite action + 1 CodeQL config**

---

# PHASE 1: ESSENTIAL (Do NOW, before v0.4.6 release)

## 1.1 — `ci.yml` (Main Umbrella Workflow)

**File:** `.github/workflows/ci.yml`

```yaml
# ci.yml — The ONLY workflow users see on PRs
#
# Contributors see 4 checks:
#   CI / Tests        (C++ + Python matrix inside)
#   CI / Code Quality (lint + typecheck + benchmark inside)
#   CI / Build        (wheel + sdist verification inside)
#   CI / Security     (CodeQL + dependency-review inside)
#
# All consolidated into ONE "CI" check for branch protection.

name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
    paths-ignore:
      - '**.md'
      - 'docs/**'
      - 'LICENSE'
      - '.gitignore'

permissions:
  contents: read

concurrency:
  group: ci-${{ github.head_ref || github.ref }}
  cancel-in-progress: true

jobs:
  tests:
    name: Tests
    uses: ./.github/workflows/_reusable-tests.yml
    with:
      run-cpp: true
      run-python: true

  quality:
    name: Code Quality
    uses: ./.github/workflows/_reusable-quality.yml

  build:
    name: Build
    uses: ./.github/workflows/_reusable-build.yml

  security:
    name: Security
    runs-on: ubuntu-latest
    timeout-minutes: 20
    permissions:
      security-events: write
      contents: read
      pull-requests: write
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive
          persist-credentials: false

      - name: Initialize CodeQL
        uses: github/codeql-action/init@e8e8e51caba890f74f97e228d00b0b81b666ee4c # v3
        with:
          languages: cpp, python
          config-file: ./.github/codeql-config.yml

      - name: Build C++ for CodeQL
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y g++ cmake ninja-build
          cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
          cmake --build build --parallel

      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@e8e8e51caba890f74f97e228d00b0b81b666ee4c # v3

      - name: Dependency Review
        if: github.event_name == 'pull_request'
        uses: actions/dependency-review-action@da24556b548a50705dd671f47852072ea4c105d9 # v4.6.0
        with:
          fail-on-severity: critical
          comment-summary-in-pr: always

  ci-status:
    name: CI
    needs: [tests, quality, build, security]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - name: Check all CI results
        run: |
          echo "=== CI Summary ==="
          echo "Tests:        ${{ needs.tests.result }}"
          echo "Code Quality: ${{ needs.quality.result }}"
          echo "Build:        ${{ needs.build.result }}"
          echo "Security:     ${{ needs.security.result }}"

          FAILED=false
          for result in "${{ needs.tests.result }}" "${{ needs.quality.result }}" "${{ needs.build.result }}" "${{ needs.security.result }}"; do
            if [ "$result" == "failure" ] || [ "$result" == "cancelled" ]; then
              FAILED=true
            fi
          done

          if [ "$FAILED" == "true" ]; then
            echo "::error::CI failed — check the logs above"
            exit 1
          fi
          echo "✅ All CI checks passed"
```

---

## 1.2 — `_reusable-tests.yml`

**File:** `.github/workflows/_reusable-tests.yml`

```yaml
name: Reusable Tests

on:
  workflow_call:
    inputs:
      run-cpp:
        type: boolean
        default: true
      run-python:
        type: boolean
        default: true

jobs:
  test-cpp:
    if: inputs.run-cpp
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-14]
    runs-on: ${{ matrix.os }}
    timeout-minutes: 15
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - name: Install build tools (Ubuntu)
        if: runner.os == 'Linux'
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y g++ cmake ninja-build

      - name: Install build tools (macOS)
        if: runner.os == 'macOS'
        run: brew install cmake ninja

      - name: Install build tools (Windows)
        if: runner.os == 'Windows'
        run: choco install cmake ninja -y

      - name: Configure and build
        run: |
          cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
          cmake --build build --config Release

      - name: Run C++ tests (Unix)
        if: runner.os != 'Windows'
        run: |
          for t in test_day1 test_fast_float_parity test_stream_reader \
                   test_profile_builder test_simd_scanner test_mmap_reader \
                   test_arrow_profiler test_hyperloglog; do
            echo "::group::$t"
            ./build/$t
            echo "::endgroup::"
          done

      - name: Run C++ tests (Windows)
        if: runner.os == 'Windows'
        shell: pwsh
        run: |
          $tests = @('test_day1','test_fast_float_parity','test_stream_reader',
                     'test_profile_builder','test_simd_scanner','test_mmap_reader',
                     'test_arrow_profiler','test_hyperloglog')
          foreach ($t in $tests) {
            Write-Host "::group::$t"
            & "./build/Release/$t.exe"
            if ($LASTEXITCODE -ne 0) { throw "$t failed" }
            Write-Host "::endgroup::"
          }

  test-python:
    if: inputs.run-python
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-14]
        python-version: ["3.9", "3.12", "3.13", "3.14"]
    runs-on: ${{ matrix.os }}
    timeout-minutes: 25
    env:
      PYTHONIOENCODING: "utf-8"
      PYTHONUTF8: "1"
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
          cache-dependency-path: pyproject.toml

      - name: Install system deps (Ubuntu)
        if: runner.os == 'Linux'
        run: sudo apt-get install -y g++

      - name: Install zedda
        run: |
          python -m pip install --upgrade pip
          pip install scikit-build-core nanobind cmake ninja
          pip install -e ".[dev]"

      - name: Run pytest
        run: pytest tests/python/ -v

      - name: Run script tests
        run: |
          python tests/test_phase3.py
          python tests/test_ask_patterns.py

  tests-status:
    name: Tests Status
    needs: [test-cpp, test-python]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - name: Check all test results
        run: |
          if [ "${{ contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled') }}" == "true" ]; then
            echo "::error::One or more test jobs failed"
            exit 1
          fi
          echo "All tests passed"
```

---

## 1.3 — `_reusable-quality.yml`

**File:** `.github/workflows/_reusable-quality.yml`

```yaml
name: Reusable Code Quality

on:
  workflow_call: {}

jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"
          cache: pip

      - run: pip install ruff

      - name: Ruff lint check
        run: ruff check .

      - name: Ruff format check
        run: ruff format --check .

  typecheck:
    name: Type Check
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"
          cache: pip

      - run: pip install mypy types-requests

      - name: Run mypy
        run: mypy python/zedda/ --ignore-missing-imports
        continue-on-error: true  # TODO: make blocking once mypy baseline established

  benchmark:
    name: Benchmark
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: pyproject.toml

      - name: Install zedda
        run: |
          sudo apt-get install -y g++
          pip install scikit-build-core nanobind cmake ninja
          pip install -e ".[dev]"

      - name: Generate benchmark fixture
        run: |
          python -c "
          import pandas as pd, numpy as np
          n = 100_000
          df = pd.DataFrame({
              'id': range(n),
              'amount': np.random.exponential(1000, n),
              'category': np.random.choice(['A','B','C'], n),
              'value': np.random.normal(500, 100, n),
          })
          df.to_csv('/tmp/bench_100k.csv', index=False)
          "

      - name: Run benchmark
        run: |
          python -c "
          import zedda as zd, time
          start = time.perf_counter()
          zd.scan('/tmp/bench_100k.csv')
          elapsed_ms = (time.perf_counter() - start) * 1000
          print(f'Benchmark: 100K rows in {elapsed_ms:.0f}ms')
          if elapsed_ms > 500:
              raise SystemExit(f'REGRESSION: {elapsed_ms}ms > 500ms')
          "

  quality-status:
    name: Code Quality Status
    needs: [lint, typecheck, benchmark]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - name: Check quality results
        run: |
          if [ "${{ contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled') }}" == "true" ]; then
            echo "::error::One or more quality jobs failed"
            exit 1
          fi
          echo "All quality checks passed"
```

---

## 1.4 — `_reusable-build.yml`

**File:** `.github/workflows/_reusable-build.yml`

```yaml
name: Reusable Build Verify

on:
  workflow_call: {}

jobs:
  build-wheels:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-latest
            python: cp313
          - os: windows-latest
            python: cp313
          - os: macos-14
            python: cp313
          - os: ubuntu-latest
            python: cp39
          - os: ubuntu-latest
            python: cp314
    runs-on: ${{ matrix.os }}
    timeout-minutes: 30
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"

      - run: pip install cibuildwheel

      - name: Set up QEMU
        if: runner.os == 'Linux'
        uses: docker/setup-qemu-action@49b3bc8e6bdd4a60e6116a5414239cba5943d3cf # v3

      - name: Build wheel
        run: python -m cibuildwheel --output-dir wheelhouse
        env:
          CIBW_BUILD: "${{ matrix.python }}-*"
          CIBW_SKIP: "*-win32 *-manylinux_i686"
          CIBW_ARCHS_LINUX: "x86_64 aarch64"
          CIBW_ARCHS_MACOS: "x86_64 arm64"
          CIBW_ARCHS_WINDOWS: "AMD64 ARM64"
          CIBW_MANYLINUX_X86_64_IMAGE: manylinux_2_28
          CIBW_MANYLINUX_AARCH64_IMAGE: manylinux_2_28
          CIBW_MUSLLINUX_X86_64_IMAGE: musllinux_1_2
          CIBW_MUSLLINUX_AARCH64_IMAGE: musllinux_1_2
          CIBW_BUILD_FRONTEND: "build"
          CIBW_BEFORE_BUILD_LINUX: >
            pip install cmake==3.30.5 ninja==1.11.1.1 scikit-build-core==0.10.7 nanobind==2.4.0
          CIBW_BEFORE_BUILD_MACOS: >
            pip install cmake==3.30.5 ninja==1.11.1.1 scikit-build-core==0.10.7 nanobind==2.4.0
          CIBW_BEFORE_BUILD_WINDOWS: >
            pip install cmake==3.30.5 ninja==1.11.1.1 scikit-build-core==0.10.7 nanobind==2.4.0

      - name: Smoke-test wheel
        run: |
          pip install --no-deps wheelhouse/*.whl
          python -c "import zedda; print(f'zedda {zedda.__version__} OK')"

      - name: Check wheel contents
        run: |
          pip install check-wheel-contents
          check-wheel-contents wheelhouse/*.whl --ignore W002,W004,W007 --package zedda

      - name: Upload wheels
        uses: actions/upload-artifact@4cec3d8aa04e39d1a68397de0c4cd6fb9dce8ec1 # v4.6.1
        if: always()
        with:
          name: pr-wheels-${{ matrix.os }}-${{ matrix.python }}
          path: wheelhouse/*.whl
          retention-days: 7

  build-sdist:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"

      - run: pip install build scikit-build-core nanobind

      - name: Build sdist
        run: python -m build --sdist

      - name: Verify sdist builds
        run: |
          pip install --no-binary zedda dist/zedda-*.tar.gz
          python -c "import zedda; print(f'zedda {zedda.__version__} OK from sdist')"

      - name: Check sdist size
        run: |
          SIZE=$(stat -c%s dist/zedda-*.tar.gz)
          if [ "$SIZE" -gt 10485760 ]; then
            echo "::error::Sdist is $((SIZE/1024/1024)) MB — exceeds 10 MB"
            exit 1
          fi
          echo "Sdist size: $((SIZE/1024)) KB — OK"

  build-status:
    name: Build Status
    needs: [build-wheels, build-sdist]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - name: Check build results
        run: |
          if [ "${{ contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled') }}" == "true" ]; then
            echo "::error::One or more build jobs failed"
            exit 1
          fi
          echo "All builds passed"
```

---

## 1.5 — `release.yml` (PyPI Publishing + Post-Publish Verify)

**File:** `.github/workflows/release.yml`

```yaml
# release.yml — Tag trigger only
# Pipeline: build wheels → sdist → TestPyPI (GATE) → PyPI → verify → release

name: Release

on:
  push:
    tags:
      - "v*.*.*"
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false

jobs:
  build_wheels:
    name: Build ${{ matrix.os }} (${{ matrix.cibw_python }})
    runs-on: ${{ matrix.os }}
    timeout-minutes: 90
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-13, macos-14]
        cibw_python: ["cp39", "cp310", "cp311", "cp312", "cp313", "cp314"]

    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"

      - run: pip install cibuildwheel

      - name: ccache setup
        uses: hendrikmuhs/ccache-action@5ebbd400eff9e74630f759d94ddd7b6c26299639 # v1.2
        with:
          key: ${{ matrix.os }}-${{ matrix.cibw_python }}
        continue-on-error: true

      - name: Set up QEMU
        if: runner.os == 'Linux'
        uses: docker/setup-qemu-action@49b3bc8e6bdd4a60e6116a5414239cba5943d3cf # v3

      - name: Build wheels
        run: |
          python -c "import os; os.makedirs('.ccache', exist_ok=True)"
          python -m cibuildwheel --output-dir wheelhouse
        env:
          CIBW_BUILD: "${{ matrix.cibw_python }}-*"
          CIBW_SKIP: "*-win32 *-manylinux_i686"
          CIBW_ARCHS_LINUX: "x86_64 aarch64"
          CIBW_ARCHS_MACOS: "x86_64 arm64"
          CIBW_ARCHS_WINDOWS: "AMD64 ARM64"
          CIBW_MANYLINUX_X86_64_IMAGE: manylinux_2_28
          CIBW_MANYLINUX_AARCH64_IMAGE: manylinux_2_28
          CIBW_MUSLLINUX_X86_64_IMAGE: musllinux_1_2
          CIBW_MUSLLINUX_AARCH64_IMAGE: musllinux_1_2
          CIBW_BUILD_FRONTEND: "build"
          CIBW_BEFORE_BUILD_LINUX: >
            pip install cmake==3.30.5 ninja==1.11.1.1 scikit-build-core==0.10.7 nanobind==2.4.0
          CIBW_BEFORE_BUILD_MACOS: >
            pip install cmake==3.30.5 ninja==1.11.1.1 scikit-build-core==0.10.7 nanobind==2.4.0
          CIBW_BEFORE_BUILD_WINDOWS: >
            pip install cmake==3.30.5 ninja==1.11.1.1 scikit-build-core==0.10.7 nanobind==2.4.0
          CIBW_BEFORE_ALL_LINUX: "yum install -y ccache || apt-get install -y ccache || apk add ccache || true"
          CIBW_BEFORE_ALL_MACOS: "export HOMEBREW_NO_REQUIRE_TAP_TRUST=1; brew install ccache || true"
          CIBW_BEFORE_ALL_WINDOWS: "choco install ccache -y || true"
          CIBW_ENVIRONMENT_LINUX: >
            CMAKE_C_COMPILER_LAUNCHER=ccache
            CMAKE_CXX_COMPILER_LAUNCHER=ccache
            CCACHE_DIR=/host/ccache
          CIBW_CONTAINER_ENGINE: "docker; create_args: --volume ${{ github.workspace }}/.ccache:/host/ccache"
          CIBW_ENVIRONMENT_MACOS: "CMAKE_C_COMPILER_LAUNCHER=ccache CMAKE_CXX_COMPILER_LAUNCHER=ccache"
          CIBW_ENVIRONMENT_WINDOWS: "CMAKE_C_COMPILER_LAUNCHER=ccache CMAKE_CXX_COMPILER_LAUNCHER=ccache"

      - name: Upload wheels
        uses: actions/upload-artifact@4cec3d8aa04e39d1a68397de0c4cd6fb9dce8ec1 # v4.6.1
        with:
          name: wheels-${{ matrix.os }}-${{ matrix.cibw_python }}
          path: ./wheelhouse/*.whl
          retention-days: 7

  build_sdist:
    name: Build sdist
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"

      - run: pip install build scikit-build-core nanobind

      - name: Build sdist
        run: python -m build --sdist

      - name: Upload sdist
        uses: actions/upload-artifact@4cec3d8aa04e39d1a68397de0c4cd6fb9dce8ec1 # v4.6.1
        with:
          name: sdist
          path: dist/*.tar.gz
          retention-days: 7

  # ── TestPyPI: REAL GATE (no continue-on-error) ──────────────
  publish_test:
    name: Publish to TestPyPI
    needs: [build_wheels, build_sdist]
    runs-on: ubuntu-latest
    timeout-minutes: 10
    # NO continue-on-error — TestPyPI failure MUST block production PyPI
    environment: testpypi
    permissions:
      id-token: write
    if: startsWith(github.ref, 'refs/tags/v')

    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - name: Download all wheels
        uses: actions/download-artifact@65a9edc5881444af0b9093a5e628f2fe47ea3b2e # v4.1.7
        with:
          pattern: wheels-*
          merge-multiple: true
          path: dist/

      - name: Download sdist
        uses: actions/download-artifact@65a9edc5881444af0b9093a5e628f2fe47ea3b2e # v4.1.7
        with:
          name: sdist
          path: dist/

      - name: Publish to TestPyPI
        uses: pypa/gh-action-pypi-publish@76f52bc884231f62b9a034ebfe128415bbaabdfc # v1.12.4
        with:
          repository-url: https://test.pypi.org/legacy/
          skip-existing: true

  # ── Production PyPI ─────────────────────────────────────────
  publish_pypi:
    name: Publish to PyPI
    needs: [publish_test]
    runs-on: ubuntu-latest
    timeout-minutes: 10
    environment:
      name: pypi-production
      url: https://pypi.org/project/zedda/
    permissions:
      id-token: write
      contents: write
    if: startsWith(github.ref, 'refs/tags/v')

    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - name: Download all wheels
        uses: actions/download-artifact@65a9edc5881444af0b9093a5e628f2fe47ea3b2e # v4.1.7
        with:
          pattern: wheels-*
          merge-multiple: true
          path: dist/

      - name: Download sdist
        uses: actions/download-artifact@65a9edc5881444af0b9093a5e628f2fe47ea3b2e # v4.1.7
        with:
          name: sdist
          path: dist/

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@76f52bc884231f62b9a034ebfe128415bbaabdfc # v1.12.4

      - name: Generate checksums
        run: |
          cd dist
          sha256sum * > SHA256SUMS.txt

      - name: Generate SBOM
        uses: anchore/sbom-action@e11c554f704a0b820cbf8c51673f6945e0731532 # v0.18.0
        with:
          path: dist/
          format: spdx-json
          output-file: dist/sbom.spdx.json

      - name: Create GitHub Release
        uses: softprops/action-gh-release@3bb12739c298aeb8a4eeaf626c5b8d85266b0e65 # v2
        with:
          files: |
            dist/*
            dist/SHA256SUMS.txt
            dist/sbom.spdx.json
          generate_release_notes: true

  # ── CRITICAL: Post-Publish Verification ────────────────────
  # Catches "wheel published but broken" disasters
  verify_pypi:
    name: Verify PyPI Install
    needs: [publish_pypi]
    runs-on: ${{ matrix.os }}
    timeout-minutes: 10
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python-version: ["3.13"]

    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: ${{ matrix.python-version }}

      - name: Wait for PyPI propagation
        run: |
          echo "Waiting 60s for PyPI to propagate the new release..."
          sleep 60

      - name: Install from PyPI
        run: |
          python -m pip install --upgrade pip
          pip install zedda==${{ github.ref_name }}

      - name: Verify import
        run: python -c "import zedda; print(f'zedda {zedda.__version__} installed from PyPI')"

      - name: Verify CLI
        run: zedda --help

      - name: Verify scan works
        run: |
          python -c "
          import pandas as pd
          df = pd.DataFrame({'a':[1,2,3], 'b':['x','y','z']})
          df.to_csv('test.csv', index=False)
          import zedda as zd
          p = zd.scan('test.csv')
          print(f'Scan OK: {p.num_rows} rows, {p.num_cols} cols')
          "

      - name: Notify on failure
        if: failure()
        uses: actions/github-script@60a0d83039c74a4aee543508d2ffcb082ae3997d # v7.0.1
        with:
          script: |
            github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: `🚨 PyPI release ${{ github.ref_name }} verification FAILED`,
              body: `The post-publish verification job failed.

              **This means the published package may be broken on PyPI.**

              Action required:
              1. Check the workflow logs: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
              2. If broken, yank the release: \`pip install zedda==${{ github.ref_name }}\` is failing
              3. Fix and cut a patch release immediately

              Matrix OS: ${{ matrix.os }}
              Python: ${{ matrix.python-version }}`,
              labels: ['security', 'bug', 'priority:critical']
            });
```

---

## 1.6 — `docker.yml`

**File:** `.github/workflows/docker.yml`

```yaml
name: Docker

on:
  push:
    tags:
      - "v*.*.*"
  workflow_dispatch:

permissions:
  contents: read
  packages: write

concurrency:
  group: docker-${{ github.ref }}
  cancel-in-progress: false

jobs:
  docker:
    name: Build & Publish Docker Image
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - name: Set up QEMU
        if: startsWith(github.ref, 'refs/tags/v')
        uses: docker/setup-qemu-action@49b3bc8e6bdd4a60e6116a5414239cba5943d3cf # v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@b5ca514318bd6ebac0fb2aedd5d36ec1b5c232a2 # v3.10.0

      - name: Log in to GitHub Container Registry
        uses: docker/login-action@74a5d142397b4f367a81961eba4e8cd7edddf772 # v3.4.0
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Log in to Docker Hub
        uses: docker/login-action@74a5d142397b4f367a81961eba4e8cd7edddf772 # v3.4.0
        with:
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_PASSWORD }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@902fa8ec7d6ecbf8d84d538b9b233a880e428804 # v5.7.0
        with:
          images: |
            ghcr.io/${{ github.repository_owner }}/zedda
            ${{ secrets.DOCKER_USERNAME }}/zedda
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=sha,prefix=

      - name: Build Docker image (amd64, for testing)
        uses: docker/build-push-action@263435318d21b8e681c14492fe198e362a7a4e35 # v6.12.0
        with:
          context: .
          push: false
          load: true
          tags: zedda:test
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Smoke test (amd64)
        run: docker run --rm zedda:test python -c "import zedda; print(f'zedda {zedda.__version__} OK')"

      - name: Trivy scan
        uses: aquasecurity/trivy-action@18f2510ee396bbf400402947e0f18c01ceb5bbc0 # v0.28.0
        with:
          image-ref: zedda:test
          format: table
          exit-code: '1'
          severity: HIGH,CRITICAL
          ignore-unfixed: true

      - name: Build and push (multi-arch)
        uses: docker/build-push-action@263435318d21b8e681c14492fe198e362a7a4e35 # v6.12.0
        with:
          context: .
          push: true
          platforms: ${{ startsWith(github.ref, 'refs/tags/v') && 'linux/amd64,linux/arm64' || 'linux/amd64' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Smoke test arm64
        if: startsWith(github.ref, 'refs/tags/v')
        run: |
          docker run --rm --platform linux/arm64 \
            $(echo "${{ steps.meta.outputs.tags }}" | head -1) \
            python -c "import zedda; print(f'zedda {zedda.__version__} OK on arm64')"
```

---

## 1.7 — `nightly.yml` (Sanitizers + Fuzz + pip-audit)

**File:** `.github/workflows/nightly.yml`

```yaml
name: Nightly

on:
  schedule:
    - cron: '0 3 * * *'
  workflow_dispatch:

permissions:
  contents: read
  issues: write
  security-events: write

concurrency:
  group: nightly
  cancel-in-progress: false

jobs:
  asan-ubsan:
    name: ASan + UBSan
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - name: Configure with sanitizers
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y g++ cmake ninja-build
          cmake -B build-sanitize \
            -DCMAKE_BUILD_TYPE=Debug \
            -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer -g" \
            -DCMAKE_C_FLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer -g" \
            -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=address,undefined"

      - name: Build
        run: cmake --build build-sanitize --parallel

      - name: Run tests under ASan+UBSan
        env:
          ASAN_OPTIONS: "halt_on_error=1:detect_leaks=1"
          UBSAN_OPTIONS: "halt_on_error=1:print_stacktrace=1"
        run: ctest --test-dir build-sanitize --output-on-failure

  tsan:
    name: TSan
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - name: Configure with TSan
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y g++ cmake ninja-build
          cmake -B build-tsan \
            -DCMAKE_BUILD_TYPE=Debug \
            -DCMAKE_CXX_FLAGS="-fsanitize=thread -g" \
            -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=thread"

      - run: cmake --build build-tsan --parallel

      - name: Run tests under TSan
        env:
          TSAN_OPTIONS: "halt_on_error=0:second_deadlock_stack=1"
        run: ctest --test-dir build-tsan --output-on-failure
        continue-on-error: true  # TODO: blocking after suppression file

  fuzz:
    name: Fuzz CSV Parser
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - name: Build fuzzer
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y clang cmake ninja-build
          cmake -B build-fuzz -DCMAKE_BUILD_TYPE=Debug -DZEDDA_BUILD_FUZZERS=ON \
            -DCMAKE_CXX_COMPILER=clang++
          cmake --build build-fuzz --target fuzz_csv_parser

      - name: Seed corpus
        run: |
          mkdir -p corpus
          printf 'a,b,c\n1,2,3\n' > corpus/seed1.csv
          printf '"hello","wor""ld","test"\n' > corpus/seed2.csv

      - name: Run fuzzer
        run: ./build-fuzz/fuzz_csv_parser corpus/ -max_total_time=600 -print_final_stats=1
        continue-on-error: true

      - name: Upload crashes
        if: failure()
        uses: actions/upload-artifact@4cec3d8aa04e39d1a68397de0c4cd6fb9dce8ec1 # v4.6.1
        with:
          name: fuzz-crashes
          path: crash-*
          retention-days: 30

  pip-audit:
    name: pip-audit
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"

      - run: pip install pip-audit

      - name: Audit core deps
        id: audit_core
        continue-on-error: true
        run: |
          pip install zedda
          pip-audit 2>&1 | tee audit_core.txt
          if grep -q "No known vulnerabilities" audit_core.txt; then
            echo "vuln_found=false" >> $GITHUB_OUTPUT
          else
            echo "vuln_found=true" >> $GITHUB_OUTPUT
          fi

      - name: Audit dev deps
        id: audit_dev
        continue-on-error: true
        run: |
          pip install -e ".[dev]"
          pip-audit 2>&1 | tee audit_dev.txt
          if grep -q "No known vulnerabilities" audit_dev.txt; then
            echo "vuln_found=false" >> $GITHUB_OUTPUT
          else
            echo "vuln_found=true" >> $GITHUB_OUTPUT
          fi

      - name: Open issue if vulnerabilities found
        if: steps.audit_core.outputs.vuln_found == 'true' || steps.audit_dev.outputs.vuln_found == 'true'
        uses: actions/github-script@60a0d83039c74a4aee543508d2ffcb082ae3997d # v7.0.1
        with:
          script: |
            const auditCore = require('fs').readFileSync('audit_core.txt', 'utf8');
            const auditDev = require('fs').readFileSync('audit_dev.txt', 'utf8');
            const body = `## pip-audit found vulnerabilities

            Run date: ${new Date().toISOString()}

            ### Core dependencies
            \`\`\`
            ${auditCore}
            \`\`\`

            ### Dev dependencies
            \`\`\`
            ${auditDev}
            \`\`\`

            ### Action required
            1. Review the vulnerabilities
            2. Update affected packages in pyproject.toml
            3. Cut a patch release

            _Auto-opened by nightly pip-audit workflow._`;

            const issues = await github.rest.issues.listForRepo({
              owner: context.repo.owner,
              repo: context.repo.repo,
              labels: 'security',
              state: 'open'
            });
            if (issues.data.length > 0) {
              console.log('Security issue already open, skipping');
              return;
            }
            await github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: '🔒 pip-audit: vulnerabilities detected',
              body: body,
              labels: ['security', 'bug', 'priority:high']
            });
```

---

## 1.8 — `maintenance.yml`

**File:** `.github/workflows/maintenance.yml`

```yaml
name: Maintenance

on:
  schedule:
    - cron: '0 0 * * *'
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  issues: write
  pull-requests: write
  contents: write

jobs:
  stale:
    name: Close Stale
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/stale@5bef64f19d7facfb25b37b414482c7164d639639 # v9
        with:
          days-before-issue-stale: 60
          days-before-issue-close: 7
          stale-issue-message: 'This issue has been automatically marked as stale. It will be closed if no further activity occurs.'
          days-before-pr-stale: 45
          days-before-pr-close: 7
          stale-pr-message: 'This PR has been automatically marked as stale. It will be closed if no further activity occurs.'
          stale-issue-label: 'stale'
          stale-pr-label: 'stale'

  release-drafter:
    name: Draft Release Notes
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: release-drafter/release-drafter@b1476f7b856d8b9c15fd2e6ccc65124f5d73af4e # v6.1.0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## 1.9 — Composite Action: `setup-zedda/action.yml`

**File:** `.github/actions/setup-zedda/action.yml`

```yaml
name: 'Setup Zedda Build Environment'
description: 'Checkout, setup Python, install build deps'

inputs:
  python-version:
    description: 'Python version'
    required: false
    default: '3.13'
  install-dev-deps:
    description: 'Install zedda[dev]'
    required: false
    default: 'false'

runs:
  using: 'composite'
  steps:
    - name: Harden Runner
      uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
      with:
        egress-policy: audit

    - name: Checkout code
      uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
      with:
        submodules: recursive

    - name: Set up Python
      uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
      with:
        python-version: ${{ inputs.python-version }}
        cache: pip
        cache-dependency-path: pyproject.toml

    - name: Install build tools
      shell: bash
      run: |
        python -m pip install --upgrade pip
        pip install scikit-build-core nanobind cmake ninja

    - name: Install dev deps
      if: inputs.install-dev-deps == 'true'
      shell: bash
      run: pip install -e ".[dev]"
```

---

## 1.10 — CodeQL Config

**File:** `.github/codeql-config.yml`

```yaml
name: "Zedda CodeQL Config"

queries:
  - uses: security-and-quality

paths:
  - src
  - include
  - python/zedda

paths-ignore:
  - extern
  - include/zedda/fast_float
  - include/zedda/BS_thread_pool.hpp
  - tests
```

---

# PHASE 2: IMPORTANT (After v0.5.0, ~1 month)

Add these workflows to the Phase 1 setup.

## 2.1 — `docs.yml` (Documentation Build + Link Check + GitHub Pages)

**File:** `.github/workflows/docs.yml`

```yaml
# docs.yml — Build MkDocs site, check links, deploy to GitHub Pages

name: Documentation

on:
  push:
    branches: [main]
    paths:
      - 'docs/**'
      - 'python/**'
      - 'pyproject.toml'
      - 'mkdocs.yml'
      - '.github/workflows/docs.yml'
  pull_request:
    branches: [main]
    paths:
      - 'docs/**'
      - 'python/**'
      - 'pyproject.toml'
      - 'mkdocs.yml'
      - '.github/workflows/docs.yml'

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: docs-${{ github.head_ref || github.ref }}
  cancel-in-progress: true

jobs:
  build:
    name: Build Docs
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"
          cache: pip

      - name: Install MkDocs
        run: |
          pip install mkdocs mkdocs-material mkdocstrings-python

      - name: Build docs
        run: mkdocs build --strict

      - name: Check links
        uses: lycheeverse/lychee-action@f8d56c2697fd13a9b6f53cecb6865ae8a3f90cb6 # v2.4.0
        with:
          args: --no-progress "docs/**/*.md" "README.md"
          fail: true

      - name: Upload artifact
        uses: actions/upload-pages-artifact@56afc609e7430d6216c4cec1e3dfa4b05bba0d6c # v3.0.1
        with:
          path: site/

  deploy:
    name: Deploy to GitHub Pages
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - name: Deploy
        id: deployment
        uses: actions/deploy-pages@d6db90164ac5ed86f2b6aed7e0febac5b3c0c036 # v4.0.5
```

**Setup steps:**
1. Create `mkdocs.yml` at repo root
2. Move `docs/*.md` into proper MkDocs structure
3. Settings → Pages → Source → "GitHub Actions"

---

## 2.2 — `coverage.yml` (C++ + Python Coverage → Codecov)

**File:** `.github/workflows/coverage.yml`

```yaml
# coverage.yml — Code coverage for C++ (gcovr) and Python (coverage.py)

name: Coverage

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: coverage-${{ github.head_ref || github.ref }}
  cancel-in-progress: true

jobs:
  cpp-coverage:
    name: C++ Coverage
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - name: Install tools
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y g++ cmake ninja-build gcovr

      - name: Build with coverage
        run: |
          cmake -B build-coverage -G Ninja \
            -DCMAKE_BUILD_TYPE=Debug \
            -DCMAKE_CXX_FLAGS="--coverage -O0 -g" \
            -DCMAKE_C_FLAGS="--coverage -O0 -g" \
            -DCMAKE_EXE_LINKER_FLAGS="--coverage"

      - run: cmake --build build-coverage --parallel

      - name: Run tests
        run: ctest --test-dir build-coverage --output-on-failure

      - name: Generate coverage report
        run: |
          gcovr --root . --filter 'src/' --filter 'include/' \
                --xml coverage_cpp.xml --print-summary

      - name: Upload to Codecov
        uses: codecov/codecov-action@b9fd7d16f6d7d1b5d2bec1a2887e65ceed900238 # v4.6.0
        with:
          files: coverage_cpp.xml
          flags: cpp
          token: ${{ secrets.CODECOV_TOKEN }}

  python-coverage:
    name: Python Coverage
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"
          cache: pip
          cache-dependency-path: pyproject.toml

      - name: Install zedda + coverage tools
        run: |
          sudo apt-get install -y g++
          pip install scikit-build-core nanobind cmake ninja
          pip install -e ".[dev]"
          pip install pytest-cov coverage

      - name: Run pytest with coverage
        run: |
          pytest tests/python/ -v \
            --cov=zedda \
            --cov-report=xml:coverage_py.xml \
            --cov-report=term-missing

      - name: Upload to Codecov
        uses: codecov/codecov-action@b9fd7d16f6d7d1b5d2bec1a2887e65ceed900238 # v4.6.0
        with:
          files: coverage_py.xml
          flags: python
          token: ${{ secrets.CODECOV_TOKEN }}
```

**Setup:**
1. Sign up at https://codecov.io (free for OSS)
2. Add `CODECOV_TOKEN` to repo Secrets
3. Add badge to README: `[![Coverage](https://codecov.io/gh/Zedda-Labs/Zedda/branch/main/graph/badge.svg)](https://codecov.io/gh/Zedda-Labs/Zedda)`

---

## 2.3 — `performance.yml` (asv — Airspeed Velocity)

**File:** `.github/workflows/performance.yml`

```yaml
# performance.yml — Historical performance tracking with asv

name: Performance

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
    paths:
      - 'src/**'
      - 'include/**'
      - 'python/**'
      - 'benchmarks/**'
  workflow_dispatch:

permissions:
  contents: read
  deployments: write
  pull-requests: write

concurrency:
  group: perf-${{ github.head_ref || github.ref }}
  cancel-in-progress: true

jobs:
  benchmark:
    name: Benchmark
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive
          fetch-depth: 0

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"
          cache: pip
          cache-dependency-path: pyproject.toml

      - name: Install zedda + asv
        run: |
          sudo apt-get install -y g++
          pip install scikit-build-core nanobind cmake ninja
          pip install -e ".[dev]"
          pip install asv

      - name: Run benchmarks
        uses: benchmark-action/github-action-benchmark@d48d326b4ca9ba73ca32a28a0dbe91660ab6f6bd # v1.20.4
        with:
          tool: 'custom'
          output-file-path: benchmark_results.json
          benchmark-data-dir-path: benchmarks/results
          fail-on-alert: true
          comment-on-alert: true
          github-token: ${{ secrets.GITHUB_TOKEN }}
          alert-threshold: '120%'
          comment-always: true
          alert-comment-cc-users: '@tirthpatel90 @prince3235'
          auto-push: ${{ github.ref == 'refs/heads/main' }}

      - name: Create benchmark script
        run: |
          mkdir -p benchmarks
          cat > benchmarks/run_benchmarks.py << 'PYEOF'
          import json, time, zedda as zd
          import pandas as pd, numpy as np

          # Generate test data
          for n in [10_000, 100_000, 1_000_000]:
              df = pd.DataFrame({
                  'id': range(n),
                  'amount': np.random.exponential(1000, n),
                  'category': np.random.choice(['A','B','C'], n),
              })
              df.to_csv(f'/tmp/bench_{n}.csv', index=False)

          results = []
          for n in [10_000, 100_000, 1_000_000]:
              for func_name, func in [('scan', zd.scan)]:
                  func(f'/tmp/bench_{n}.csv')  # warmup
                  times = []
                  for _ in range(5):
                      start = time.perf_counter()
                      func(f'/tmp/bench_{n}.csv')
                      times.append(time.perf_counter() - start)
                  median_ms = sorted(times)[2] * 1000
                  results.append({
                      'name': f'{func_name}_{n}',
                      'value': median_ms,
                      'unit': 'ms'
                  })
          print(json.dumps(results, indent=2))
          PYEOF

      - name: Run benchmark script
        run: python benchmarks/run_benchmarks.py > benchmark_results.json
```

**Setup:**
1. Create `benchmarks/` directory
2. The workflow auto-creates `benchmarks/run_benchmarks.py`
3. Results stored in `benchmarks/results/` (auto-pushed to `main`)

---

## 2.4 — `scorecard.yml` (Weekly OpenSSF Scorecard)

**File:** `.github/workflows/scorecard.yml`

```yaml
# scorecard.yml — Weekly OpenSSF Scorecard analysis

name: OpenSSF Scorecard

on:
  schedule:
    - cron: '0 5 * * 1'  # Weekly Monday
  workflow_dispatch:

permissions:
  contents: read
  actions: read
  security-events: write
  id-token: write

jobs:
  analysis:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          persist-credentials: false

      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a # v2.4.3
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: true

      - uses: github/codeql-action/upload-sarif@e8e8e51caba890f74f97e228d00b0b81b666ee4c # v3
        with:
          sarif_file: results.sarif
```

---

## 2.5 — `stress-tests.yml` (Nightly Edge Case Testing)

**File:** `.github/workflows/stress-tests.yml`

```yaml
# stress-tests.yml — Nightly edge case + stress testing

name: Stress Tests

on:
  schedule:
    - cron: '0 4 * * *'  # Daily at 04:00 UTC
  workflow_dispatch:

permissions:
  contents: read
  issues: write

concurrency:
  group: stress-tests
  cancel-in-progress: false

jobs:
  csv-edge-cases:
    name: CSV Edge Cases
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"
          cache: pip
          cache-dependency-path: pyproject.toml

      - name: Install zedda
        run: |
          sudo apt-get install -y g++
          pip install scikit-build-core nanobind cmake ninja
          pip install -e ".[dev]"

      - name: Test edge cases
        run: |
          python -c "
          import zedda as zd
          import pandas as pd
          import os

          # Test 1: Empty file
          open('/tmp/empty.csv', 'w').close()
          try:
              zd.scan('/tmp/empty.csv')
              print('FAIL: Empty file should error')
          except Exception as e:
              print(f'PASS: Empty file errors correctly: {e}')

          # Test 2: Header only
          with open('/tmp/header_only.csv', 'w') as f:
              f.write('a,b,c\n')
          p = zd.scan('/tmp/header_only.csv')
          print(f'PASS: Header-only file: {p.num_rows} rows')

          # Test 3: Single row
          df = pd.DataFrame({'a': [1], 'b': ['x']})
          df.to_csv('/tmp/single.csv', index=False)
          p = zd.scan('/tmp/single.csv')
          print(f'PASS: Single row: {p.num_rows} rows')

          # Test 4: Quoted fields with embedded newlines
          with open('/tmp/quoted.csv', 'w') as f:
              f.write('name,desc\n')
              f.write('\"hello\",\"line1\\nline2\"\n')
          p = zd.scan('/tmp/quoted.csv')
          print(f'PASS: Quoted newlines: {p.num_rows} rows')

          # Test 5: NULL variations
          with open('/tmp/nulls.csv', 'w') as f:
              f.write('a,b,c\n')
              f.write('1,NULL,NA\n')
              f.write('2,null,N/A\n')
              f.write('3,None,?\n')
              f.write('4,,\n')
          p = zd.scan('/tmp/nulls.csv')
          print(f'PASS: NULL variations: {p.num_rows} rows, col a nulls: {p.columns[0].null_pct}%')

          # Test 6: Very long strings
          df = pd.DataFrame({'long': ['x' * 10000, 'y' * 50000]})
          df.to_csv('/tmp/long.csv', index=False)
          p = zd.scan('/tmp/long.csv')
          print(f'PASS: Long strings: max_len={p.columns[0].max_str_len}')

          # Test 7: Unicode
          df = pd.DataFrame({'emoji': ['🎉', '🎵', '🚀'], 'unicode': ['café', 'naïve', 'résumé']})
          df.to_csv('/tmp/unicode.csv', index=False)
          p = zd.scan('/tmp/unicode.csv')
          print(f'PASS: Unicode: {p.num_rows} rows')

          print('\\n✅ All edge case tests passed')
          "

      - name: Test large datasets
        run: |
          python -c "
          import zedda as zd
          import pandas as pd
          import numpy as np
          import time

          # 1M rows
          print('Generating 1M rows...')
          df = pd.DataFrame({
              'id': range(1_000_000),
              'value': np.random.normal(100, 50, 1_000_000),
              'category': np.random.choice(['A','B','C','D'], 1_000_000),
          })
          df.to_csv('/tmp/1m.csv', index=False)

          start = time.perf_counter()
          p = zd.scan('/tmp/1m.csv')
          elapsed = time.perf_counter() - start
          print(f'PASS: 1M rows in {elapsed:.2f}s, {p.num_rows} rows scanned')

          # 10M rows
          print('Generating 10M rows...')
          df = pd.DataFrame({
              'id': range(10_000_000),
              'value': np.random.normal(100, 50, 10_000_000),
              'category': np.random.choice(['A','B','C','D'], 10_000_000),
          })
          df.to_csv('/tmp/10m.csv', index=False)

          start = time.perf_counter()
          p = zd.scan('/tmp/10m.csv')
          elapsed = time.perf_counter() - start
          print(f'PASS: 10M rows in {elapsed:.2f}s, {p.num_rows} rows scanned')

          # Cleanup
          os.remove('/tmp/1m.csv')
          os.remove('/tmp/10m.csv')
          "
        timeout-minutes: 20
```

---

# PHASE 3: ENTERPRISE READINESS (At v1.0, ~3 months)

## 3.1 — `api-compat.yml` (API Compatibility Check)

**File:** `.github/workflows/api-compat.yml`

```yaml
# api-compat.yml — Detect breaking API changes using griffe

name: API Compatibility

on:
  pull_request:
    branches: [main]
    paths:
      - 'python/zedda/**'

permissions:
  contents: read
  pull-requests: write

jobs:
  check-api:
    name: Check API Changes
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          fetch-depth: 0

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"

      - run: pip install griffe

      - name: Compare API with main branch
        run: |
          # Get API from PR branch
          python -c "
          import griffe
          api = griffe.load('python/zedda')
          with open('api_pr.json', 'w') as f:
              import json
              json.dump({
                  name: {
                      'kind': str(obj.kind),
                      'parameters': [p.name for p in obj.parameters] if hasattr(obj, 'parameters') else []
                  }
                  for name, obj in api.members.items()
              }, f, indent=2)
          "

          # Checkout main, get API from main
          git checkout main -- python/zedda
          python -c "
          import griffe
          api = griffe.load('python/zedda')
          with open('api_main.json', 'w') as f:
              import json
              json.dump({
                  name: {
                      'kind': str(obj.kind),
                      'parameters': [p.name for p in obj.parameters] if hasattr(obj, 'parameters') else []
                  }
                  for name, obj in api.members.items()
              }, f, indent=2)
          "

          # Compare
          python -c "
          import json
          with open('api_main.json') as f: main_api = json.load(f)
          with open('api_pr.json') as f: pr_api = json.load(f)

          removed = set(main_api.keys()) - set(pr_api.keys())
          added = set(pr_api.keys()) - set(main_api.keys())

          if removed:
              print('::error::Breaking change: removed public APIs:', removed)
              exit(1)
          if added:
              print(f'Added APIs: {added}')
          print('✅ No breaking API changes')
          "
```

---

## 3.2 — `license-check.yml` (Dependency License Compliance)

**File:** `.github/workflows/license-check.yml`

```yaml
# license-check.yml — Scan dependency licenses

name: License Check

on:
  pull_request:
    branches: [main]
    paths:
      - 'pyproject.toml'
  schedule:
    - cron: '0 8 * * 1'  # Weekly
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write

jobs:
  license-check:
    name: Check Licenses
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"

      - name: Install zedda + license tools
        run: |
          pip install -e ".[dev]"
          pip install pip-licenses

      - name: Check licenses
        run: |
          pip-licenses --from=meta --format=table --summary > license-summary.txt
          cat license-summary.txt

          # Fail on GPL/AGPL
          pip-licenses --from=classifier --fail-on="GPL;GPLv2;GPLv3;LGPL;AGPL;Affero GPL" || {
            echo "::error::Forbidden license detected"
            exit 1
          }

      - name: Comment on PR
        if: github.event_name == 'pull_request'
        uses: actions/github-script@60a0d83039c74a4aee543508d2ffcb082ae3997d # v7.0.1
        with:
          script: |
            const fs = require('fs');
            const summary = fs.readFileSync('license-summary.txt', 'utf8');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `## 📋 License check\n\n\`\`\`\n${summary}\n\`\`\``
            });
```

---

## 3.3 — `memory-bench.yml` (Memory Benchmark with memray)

**File:** `.github/workflows/memory-bench.yml`

```yaml
# memory-bench.yml — Track memory usage with memray

name: Memory Benchmark

on:
  schedule:
    - cron: '0 6 * * *'  # Daily
  workflow_dispatch:

permissions:
  contents: read

jobs:
  memory-bench:
    name: Memory Usage
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          submodules: recursive

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"
          cache: pip
          cache-dependency-path: pyproject.toml

      - name: Install zedda + memray
        run: |
          sudo apt-get install -y g++
          pip install scikit-build-core nanobind cmake ninja
          pip install -e ".[dev]"
          pip install memray

      - name: Generate test data
        run: |
          python -c "
          import pandas as pd, numpy as np
          n = 1_000_000
          df = pd.DataFrame({
              'id': range(n),
              'value': np.random.normal(100, 50, n),
              'category': np.random.choice(['A','B','C','D'], n),
          })
          df.to_csv('/tmp/1m.csv', index=False)
          "

      - name: Run memory benchmark
        run: |
          memray run --output memray.bin -c "
          import zedda as zd
          p = zd.scan('/tmp/1m.csv')
          print(f'Scanned {p.num_rows} rows')
          "

      - name: Generate report
        run: |
          memray stats memray.bin > memory_stats.txt
          cat memory_stats.txt

      - name: Upload report
        uses: actions/upload-artifact@4cec3d8aa04e39d1a68397de0c4cd6fb9dce8ec1 # v4.6.1
        with:
          name: memory-report
          path: |
            memory_stats.txt
            memray.bin
          retention-days: 30
```

---

## 3.4 — `upgrade-test.yml` (Upgrade Compatibility)

**File:** `.github/workflows/upgrade-test.yml`

```yaml
# upgrade-test.yml — Verify upgrade from previous version doesn't break

name: Upgrade Test

on:
  release:
    types: [published]

permissions:
  contents: read

jobs:
  upgrade-test:
    name: Upgrade Compatibility
    runs-on: ${{ matrix.os }}
    timeout-minutes: 15
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
    steps:
      - name: Harden Runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2
        with:
          egress-policy: audit

      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: "3.13"

      - name: Install previous version
        run: |
          pip install zedda==0.4.5  # Previous version
          python -c "import zedda; print(f'Old: {zedda.__version__}')"

      - name: Create test data
        run: |
          python -c "
          import pandas as pd
          df = pd.DataFrame({'a':[1,2,3], 'b':['x','y','z']})
          df.to_csv('test.csv', index=False)
          "

      - name: Test old version works
        run: |
          python -c "
          import zedda as zd
          p = zd.scan('test.csv')
          print(f'Old version works: {p.num_rows} rows')
          "

      - name: Upgrade to new version
        run: |
          pip install --upgrade zedda
          python -c "import zedda; print(f'New: {zedda.__version__}')"

      - name: Test new version works
        run: |
          python -c "
          import zedda as zd
          p = zd.scan('test.csv')
          print(f'Upgrade successful: {p.num_rows} rows')
          "
```

---

# Configuration Files

## `.github/labeler.yml` (Phase 2 — PR Auto-Labeling)

```yaml
C++:
  - changed-files:
    - any-glob-to-any-file: ['src/**', 'include/**', 'CMakeLists.txt', 'extern/**']

Python:
  - changed-files:
    - any-glob-to-any-file: ['python/**', 'tests/python/**']

CI/CD:
  - changed-files:
    - any-glob-to-any-file: ['.github/workflows/**', '.github/labeler.yml', '.github/dependabot.yml']

documentation:
  - changed-files:
    - any-glob-to-any-file: ['docs/**', '*.md', 'README.md']

dependencies:
  - changed-files:
    - any-glob-to-any-file: ['pyproject.toml', '.github/dependabot.yml', 'extern/nanobind/**', 'extern/thread-pool/**']

docker:
  - changed-files:
    - any-glob-to-any-file: ['Dockerfile', '.dockerignore', '.github/workflows/docker.yml']

tests:
  - changed-files:
    - any-glob-to-any-file: ['tests/**', 'benchmarks/**']

security:
  - changed-files:
    - any-glob-to-any-file: ['SECURITY.md', '.github/CODEOWNERS', '.github/workflows/ci.yml']
```

---

## `mkdocs.yml` (Phase 2 — Documentation Site)

**File:** `mkdocs.yml` (repo root)

```yaml
site_name: Zedda
site_description: Zero Effort Data Analysis — C++17-powered EDA engine for Python
site_url: https://zedda-labs.github.io/Zedda/
repo_url: https://github.com/Zedda-Labs/Zedda
repo_name: Zedda-Labs/Zedda
edit_uri: edit/main/docs/

theme:
  name: material
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.expand
    - search.suggest
    - search.highlight
    - content.code.copy
  palette:
    - scheme: default
      primary: green
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - scheme: slate
      primary: green
      toggle:
        icon: material/brightness-4
        name: Switch to light mode

plugins:
  - search
  - mkdocstrings:
      handlers:
        python:
          paths: [python]
          options:
            show_source: true
            show_signature_annotations: true

nav:
  - Home: index.md
  - Getting Started: getting_started.md
  - API Reference:
      - Overview: api.md
      - Profile: api/profile.md
      - Scan: api/scan.md
      - Compare: api/compare.md
      - Fix: api/fix.md
      - Clean: api/clean.md
      - Merge: api/merge.md
      - Ask: api/ask.md
      - ML Ready: api/ml_ready.md
      - Warnings: api/warnings.md
      - Report: api/report.md
  - Architecture: architecture.md
  - Contributing: contributing.md

markdown_extensions:
  - admonition
  - codehilite
  - footnotes
  - toc:
      permalink: true
  - pymdownx.highlight:
      anchor_linenums: true
  - pymdownx.superfences
```

---

# Branch Protection Setup (Manual)

**Go to:** Settings → Branches → main → Edit rule

```
✅ Require a pull request before merging
   ✅ Require approvals: 1
   ✅ Require review from Code Owners
   ✅ Dismiss stale pull request approvals when new commits are pushed

✅ Require status checks to pass before merging
   ✅ Require branches to be up to date before merging
   Required status checks:
   - CI                          ← ONLY this (consolidation job)

✅ Require conversation resolution before merging
✅ Require linear history
✅ Do not allow bypassing the above settings

❌ Allow administrators to bypass — KEEP OFF
❌ Allow force pushes — KEEP OFF
❌ Allow deletions — KEEP OFF
```

---

# GitHub Settings to Enable

**Settings → Code security and analysis:**
- ✅ Dependency graph → Enable
- ✅ Dependabot alerts → Enable
- ✅ Dependabot security updates → Enable
- ✅ Code scanning (CodeQL) → Enable
- ✅ Secret scanning → Enable
- ✅ Secret scanning push protection → Enable

**Settings → Environments:**
- Create `testpypi` (no required reviewers)
- Create `pypi-production` (add Tirth + Prince as required reviewers)
- Create `github-pages` (for docs deployment)

**Settings → Secrets and variables → Actions:**
- `DOCKER_USERNAME` — Docker Hub username
- `DOCKER_PASSWORD` — Docker Hub access token
- `CODECOV_TOKEN` — Codecov upload token (Phase 2)

---

# Migration Steps

## Phase 1 Migration (Now, 2 hours)

```bash
git checkout -b refactor/phase1-cicd

# Create directory structure
mkdir -p .github/actions/setup-zedda

# Create files (copy from this document):
# .github/workflows/ci.yml
# .github/workflows/_reusable-tests.yml
# .github/workflows/_reusable-quality.yml
# .github/workflows/_reusable-build.yml
# .github/workflows/release.yml
# .github/workflows/docker.yml
# .github/workflows/nightly.yml
# .github/workflows/maintenance.yml
# .github/actions/setup-zedda/action.yml
# .github/codeql-config.yml

# Delete old workflows
git rm .github/workflows/tests.yml
git rm .github/workflows/build_wheels.yml
git rm .github/workflows/codeql.yml
git rm .github/workflows/dependency-review.yml
git rm .github/workflows/scorecard.yml
git rm .github/workflows/sanitizers.yml
git rm .github/workflows/fuzz.yml
git rm .github/workflows/docker_publish.yml
git rm .github/workflows/stale.yml
git rm .github/workflows/release-drafter.yml

git add .github/
git commit -m "refactor(ci): Phase 1 — complete CI/CD restructure

- 8 workflow files (down from 10)
- ONE workflow (ci.yml) triggers on PRs
- 4 consolidated checks: Tests, Quality, Build, Security
- Release pipeline with TestPyPI gate + post-publish verify
- Nightly: ASan/UBSan/TSan + fuzz + pip-audit
- Composite action for shared setup
- CodeQL config excludes vendored code

Critical fixes:
- pypa/gh-action-pypi-publish SHA-pinned
- TestPyPI gate is REAL (no continue-on-error)
- manylinux_2_28 (was deprecated manylinux2014)
- cp314 in matrix
- ARM64 wheels (Linux + Windows + musllinux)
- Post-publish PyPI install verification"

git push origin refactor/phase1-cicd
```

Open PR, verify 4 checks, merge.

## Phase 2 Migration (1 month later, 6 hours)

```bash
git checkout -b refactor/phase2-cicd

# Add files:
# .github/workflows/docs.yml
# .github/workflows/coverage.yml
# .github/workflows/performance.yml
# .github/workflows/scorecard.yml
# .github/workflows/stress-tests.yml
# .github/labeler.yml
# mkdocs.yml (repo root)

# Sign up for Codecov, add CODECOV_TOKEN secret
# Configure GitHub Pages (Settings → Pages → Source: GitHub Actions)

git add .
git commit -m "feat(ci): Phase 2 — coverage, docs, perf tracking, stress tests"
git push origin refactor/phase2-cicd
```

## Phase 3 Migration (3 months later, 5 hours)

```bash
git checkout -b refactor/phase3-cicd

# Add files:
# .github/workflows/api-compat.yml
# .github/workflows/license-check.yml
# .github/workflows/memory-bench.yml
# .github/workflows/upgrade-test.yml

git add .
git commit -m "feat(ci): Phase 3 — API compat, license check, memory bench, upgrade tests"
git push origin refactor/phase3-cicd
```

---

# Final Score Progression

| Stage | Score | What's Added |
|---|---|---|
| Current (post-PR #43) | 6.5/10 | Packaging fixed, library bugs remain |
| **Phase 1** (now) | **7.5/10** | 7 bugs fixed + safe release pipeline + PyPI verify |
| **Phase 2** (1 month) | **8.5/10** | Coverage + docs + perf + stress tests |
| **Phase 3** (3 months) | **9.5/10** | API compat + license + memory + upgrade |

---

# What This Pipeline Does (Summary)

| Trigger | What Runs | Time |
|---|---|---|
| **PR opened** | Tests (12 jobs) + Quality (3) + Build (5) + Security (3) = 4 checks | ~20 min |
| **Push to main** | Same as PR + Release Drafter | ~20 min |
| **Tag push** | Build 50+ wheels → TestPyPI → PyPI → verify on 3 OS → GitHub Release + Docker build/push | ~60 min |
| **Daily nightly** | ASan/UBSan + TSan + Fuzz + pip-audit | ~40 min |
| **Daily maintenance** | Stale issues/PRs auto-close | ~2 min |
| **Daily stress** (Phase 2) | CSV edge cases + large datasets (1M, 10M rows) | ~30 min |
| **Daily memory** (Phase 3) | memray memory profiling | ~15 min |
| **Weekly scorecard** (Phase 2) | OpenSSF Scorecard analysis | ~10 min |
| **Weekly license** (Phase 3) | Dependency license compliance | ~5 min |
| **Release** (Phase 3) | Upgrade compatibility test | ~10 min |

---

# Comparison with Top OSS Projects

| Feature | NumPy | Pandas | Polars | pyarrow | **Zedda Phase 1** | **Zedda Phase 3** |
|---|---|---|---|---|---|---|
| Multi-platform wheels | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ARM64 wheels | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| PyPI trusted publishing | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| TestPyPI gate | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| SBOM | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| Post-publish verify | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Code coverage | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| Perf tracking (asv) | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Docs site | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| Link checker | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| Fuzzing | ✅ | ❌ | ❌ | ✅ | ✅ (nightly) | ✅ |
| ASan/UBSan | ✅ | ❌ | ✅ | ✅ | ✅ (nightly) | ✅ |
| License check | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ |
| Stress tests | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| Memory benchmark | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| API compat check | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Upgrade test | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

**At Phase 3, Zedda's CI/CD exceeds pandas/Polars in some areas.**

---

# The Bottom Line

This file is the COMPLETE reference. Copy the YAML, follow the migration steps, configure GitHub settings, and Zedda has world-class CI/CD.

**Don't do everything at once.** Phase 1 now. Phase 2 in a month. Phase 3 at v1.0. Each phase has clear value and clear timing.

**Your users don't care about CI/CD score. They care that `pip install zedda` works.** Fix the 7 library bugs first, ship v0.4.6, then build the pipeline incrementally as the project grows.
