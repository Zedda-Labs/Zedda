<p align="center">
  <img src="docs/logo.png" alt="ZEDDA Logo" width="420">
</p>

<h3 align="center">Zero Effort Data Analysis</h3>

<p align="center">
  <strong>Profile any dataset in seconds — powered by a C++ parallel engine.</strong><br>
  CSV &bull; Parquet &bull; Arrow &nbsp;|&nbsp; 1TB files &nbsp;|&nbsp; One line of code
</p>

<p align="center">
  <a href="https://pypi.org/project/zedda/"><img src="https://img.shields.io/pypi/v/zedda?color=blue&label=PyPI" alt="PyPI"></a>
  <a href="https://pypi.org/project/zedda/"><img src="https://img.shields.io/pypi/pyversions/zedda?color=green" alt="Python"></a>
  <a href="https://github.com/prince3235/fasteda/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License"></a>
  <a href="https://github.com/prince3235/fasteda/actions"><img src="https://img.shields.io/github/actions/workflow/status/prince3235/fasteda/tests.yml?label=Tests" alt="Tests"></a>
</p>

---

## Why ZEDDA?

Every Data Scientist's first step is **understanding the data**. But existing tools force a painful tradeoff:

| Tool | 500MB CSV | 5GB Parquet | RAM Usage |
|------|-----------|-------------|-----------|
| Pandas Profiling | 12 min | ❌ Crash | 8 GB+ |
| ydata-profiling | 8 min | ❌ Crash | 6 GB+ |
| **ZEDDA** | **3 sec** | **5 sec** | **< 200 MB** |

ZEDDA achieves this through a **multi-threaded C++ core** that processes data in parallel, combined with **intelligent sampling** that gives you statistically accurate results without reading every single row.

---

## Quick Start

### Install

```bash
pip install zedda
```

### One Line — That's It

```python
import zedda as zd

zd.profile("transactions.csv")
```

**Output:**

```
⚡ zedda v0.2.0
Scanning transactions.csv...

┌─────────── Dataset Overview ⚡ SAMPLED ───────────┐
│ File:    transactions.csv                          │
│ ⚠  SAMPLED MODE  (stratified, exact nulls & range)│
│ Rows:    6,362,620                                 │
│ Cols:    11  (8 numeric, 3 string)                 │
│ Nulls:   0.0%  (0 cells)                           │
│ Scanned: 4,231 ms                                  │
└────────────────────────────────────────────────────┘

 Column           Type   Nulls   Mean (±95% CI)       Min         Max       Flags
 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 step             int    0.0%    192.6 ± 0.24         1           353       ok
 amount           float  0.0%    1.793e+05 ± 701      0           1.55e+07  HIGH CARD
 oldbalanceOrg    float  0.0%    8.553e+05 ± 5,714    0           3.894e+07 ok
 isFraud          int    0.0%    0.000659 ± 5.03e-05  0           1         ok
 ...

ℹ  Means show 95% confidence interval. Null counts and min/max are exact (from Parquet footer).
```

---

## Features

### 🚀 Blazing Fast C++ Core

ZEDDA's profiling engine is written entirely in **C++17** and compiled natively for your platform. It uses [`BS::thread_pool`](https://github.com/bshoshany/thread-pool) to parse data across **all CPU cores simultaneously** — achieving 5–8x speedup over single-threaded Python.

```
Python (Pandas):  1 core  → 12 seconds for 500MB
ZEDDA (C++):      8 cores → 1.5 seconds for 500MB
```

### 📊 Intelligent Auto-Sampling

Files over **500 MB** automatically trigger **stratified sampling** — ZEDDA reads 1 million representative rows instead of the entire file. This is configurable:

```python
# Auto (default) — ZEDDA decides based on file size
zd.profile("huge_file.csv")

# Force exact scan — no sampling, read every row
zd.profile("huge_file.csv", sample_size=-1)

# Custom sample — e.g. 5 million rows
zd.profile("huge_file.csv", sample_size=5_000_000)
```

**Why is this safe?**
- **Statistics guarantees it:** 1M rows is a massive sample — error margin is typically < 0.1%.
- **95% Confidence Intervals:** Every mean is shown as `Mean ± CI` so you can see exactly how precise the estimate is.
- **Parquet Footer Cheat Code:** Min, Max, and Null counts are always **exact** — read directly from Parquet metadata in milliseconds, even for TB-scale files.

### 🔍 Smart Column Flags

ZEDDA automatically detects data quality issues and flags them:

| Flag | Meaning | When |
|------|---------|------|
| `HIGH NULL` | Column has too many missing values | Null% > 20% |
| `CONST` | Column has only one unique value | Useless for ML |
| `HIGH CARD` | Column has very high cardinality | May need encoding |

### ⚖️ Dataset Comparison

Compare two datasets (e.g., train vs test, v1 vs v2) and detect **schema changes, null rate shifts, and distribution drift**:

```python
zd.compare("train.csv", "test.csv")
```

```
⚡ zedda compare
A: train.csv  (800,000 rows)
B: test.csv   (200,000 rows)

 Column       Type A  Type B  Nulls A  Nulls B  Mean A    Mean B    Drift
 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 age          int     int     0.0%     0.0%     29.7      29.4      ok
 fare         float   float   0.0%     2.1%     32.2      35.8      SHIFT
 cabin        str     MISSING 77.1%    —        —         —         REMOVED
 embarked     str     str     0.2%     0.0%     —         —         ok
```

- **`DRIFT`**: Mean shifted significantly (z-score > 1.0) — model retraining may be needed.
- **`SHIFT`**: Moderate change detected (z-score > 0.3).
- **`NEW` / `REMOVED`**: Column added or dropped between datasets.

### 🖥️ CLI — Profile From Your Terminal

No Python script needed. Profile any file directly from the command line:

```bash
# Profile a file
zedda run data.csv

# Compare two files
zedda compare train.csv test.csv

# Quick file info (rows, size)
zedda info data.csv

# AI-powered insights (requires OPENAI_API_KEY)
zedda run data.csv --ai
```

---

## API Reference

### `zd.profile(path, sample_size=None)`

Scan a file, print a beautiful terminal report, and return the result.

```python
result = zd.profile("data.csv")
# Prints colored table to terminal
# Returns DatasetProfile object
```

### `zd.scan(path, sample_size=None)`

Scan a file and return the result **without** printing.

```python
p = zd.scan("data.parquet")

# Access dataset-level stats
print(p.num_rows)         # 6362620
print(p.num_cols)         # 11
print(p.scan_time_ms)     # 4231.5
print(p.is_sampled)       # True

# Access column-level stats
for col in p.columns:
    print(col.name)       # "amount"
    print(col.type_str)   # "float"
    print(col.mean)       # 179329.4
    print(col.stddev)     # 603858.2
    print(col.val_min)    # 0.0
    print(col.val_max)    # 15500000.0
    print(col.null_pct)   # 0.0
    print(col.unique_approx)  # 978372
```

### `zd.compare(path_a, path_b, sample_size=None)`

Compare two datasets side by side with drift detection.

```python
zd.compare("january_sales.csv", "february_sales.csv")
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | required | Path to CSV, Parquet, or Arrow file |
| `sample_size` | `int` | `None` | Max rows to sample. `None` = auto, `-1` = read all |

### Supported Formats

| Format | Extension | Zero-Copy |
|--------|-----------|-----------|
| CSV | `.csv` | — |
| Parquet | `.parquet` | ✅ via Arrow C Data Interface |
| Arrow IPC | `.arrow` | ✅ via Arrow C Data Interface |

---

## How It Works

```
┌──────────────────────────────────────────────────────────┐
│                    Python API Layer                       │
│           zd.profile() / zd.scan() / zd.compare()        │
└────────────────────────┬─────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │   Auto-Sampling     │
              │   Decision Engine   │
              │   (>500MB = sample) │
              └──────────┬──────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    ┌──────────┐  ┌───────────┐  ┌──────────┐
    │ CSV Path │  │  Parquet   │  │  Arrow   │
    │          │  │  Path      │  │  Path    │
    └────┬─────┘  └─────┬─────┘  └────┬─────┘
         │              │              │
         ▼              ▼              ▼
    ┌──────────┐  ┌───────────┐  ┌──────────┐
    │ C++ Multi│  │ PyArrow   │  │ PyArrow  │
    │ Threaded │  │ Stratified│  │ Batched  │
    │ Chunked  │  │ Row Group │  │ Reader   │
    │ Parser   │  │ Sampling  │  │          │
    └────┬─────┘  └─────┬─────┘  └────┬─────┘
         │              │              │
         └──────────────┼──────────────┘
                        ▼
              ┌───────────────────┐
              │  C++ Profile      │
              │  Builder Engine   │
              │  (BS::thread_pool)│
              │  ──────────────── │
              │  • Welford Online │
              │    Mean/Variance  │
              │  • HyperLogLog   │
              │    Unique Approx  │
              │  • Streaming     │
              │    Min/Max/Nulls  │
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │  DatasetProfile   │
              │  Result Object    │
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │  Rich Terminal    │
              │  Pretty Printer   │
              │  (colored tables) │
              └───────────────────┘
```

### Key Algorithms

| Component | Algorithm | Why |
|-----------|-----------|-----|
| Mean & Variance | Welford's Online Algorithm | Numerically stable, single-pass |
| Unique Count | HyperLogLog (approx) | O(1) memory, works on billions of values |
| Thread Pool | BS::thread_pool | Zero-overhead, lock-free task scheduling |
| Parquet I/O | Arrow C Data Interface | True zero-copy — no serialization |
| Sampling | Stratified Row Groups | Covers start, middle, and end of file |

---

## Project Structure

```
zedda/
├── src/core/               # C++ engine
│   ├── profile_builder.cpp  # Multi-threaded profiling logic
│   ├── arrow_profiler.cpp   # Arrow C Data Interface consumer
│   └── stream_reader.cpp    # CSV chunked reader
├── include/zedda/           # C++ headers
│   ├── profile_builder.hpp
│   ├── profile_result.hpp   # DatasetProfile struct
│   ├── stream_reader.hpp
│   └── BS_thread_pool.hpp   # Thread pool (MIT, header-only)
├── python/zedda/            # Python package
│   ├── __init__.py          # Public API (profile, scan, compare)
│   └── cli.py               # Typer CLI app
├── tests/                   # Test suites
├── CMakeLists.txt           # Build configuration
└── pyproject.toml           # Package metadata
```

---

## Development

### Build from Source

```bash
# Clone with submodules
git clone --recursive https://github.com/prince3235/fasteda.git
cd fasteda

# Install in editable mode
pip install -e . --no-build-isolation

# Run tests
python -X utf8 tests/test_phase3.py
```

### Requirements

- **Python** ≥ 3.9
- **C++ Compiler** with C++17 support (MSVC 19+, GCC 9+, Clang 10+)
- **CMake** ≥ 3.21

---

## Roadmap

- [x] **Phase 1** — Multi-threaded CSV parsing (5–8x speedup)
- [x] **Phase 2** — Zero-copy Parquet via Arrow C Data Interface
- [x] **Phase 3** — Intelligent Sampling Engine (1TB support)
- [ ] **Phase 4** — SIMD/AVX-512 vectorized numeric parsing
- [ ] **Phase 5** — Interactive HTML reports & dashboards
- [ ] **Phase 6** — AI-powered data insights (GPT integration)

---

## Contributing

We welcome contributions! Here's how:

1. **Fork** the repo
2. **Create** your feature branch (`git checkout -b feat/amazing-feature`)
3. **Commit** your changes (`git commit -m 'feat: add amazing feature'`)
4. **Push** to the branch (`git push origin feat/amazing-feature`)
5. **Open** a Pull Request

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

<p align="center">
  Built with ❤️ and C++ by <a href="https://github.com/prince3235">Prince Patel</a>
</p>
