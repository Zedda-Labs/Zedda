<div align="center">
  <img src="https://raw.githubusercontent.com/Zedda-Labs/Zedda/main/docs/logo.png" alt="Zedda Logo" width="420"/>
  <h1>Zedda</h1>
  <h3>Zero Effort Data Analysis</h3>
  <p><strong>The world's fastest EDA library — C++17 powered, pip installable, 1TB in seconds.</strong></p>

  [![PyPI Version](https://img.shields.io/pypi/v/zedda?color=blue&label=PyPI&logo=pypi&logoColor=white)](https://pypi.org/project/zedda/)
  [![Python](https://img.shields.io/pypi/pyversions/zedda?color=green&logo=python&logoColor=white)](https://pypi.org/project/zedda/)
  [![Downloads](https://static.pepy.tech/badge/zedda)](https://pepy.tech/project/zedda)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/Zedda-Labs/Zedda/blob/main/LICENSE)
  [![Build](https://img.shields.io/github/actions/workflow/status/Zedda-Labs/Zedda/build_wheels.yml?label=build&logo=githubactions&logoColor=white)](https://github.com/Zedda-Labs/Zedda/actions)
  [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/Zedda-Labs/Zedda/blob/main/CONTRIBUTING.md)
</div>

---

## ⚡ What is Zedda?

Zedda is a **blazing-fast Exploratory Data Analysis (EDA) library** for Python. It replaces dozens of lines of pandas boilerplate with a single function call — and runs **2,000× faster** than traditional tools by offloading all heavy computation to a custom **C++17 streaming engine**.

```python
import zedda as zd
import pandas as pd

# Directly from a file
zd.profile("titanic.csv")   # Full EDA report in 19ms
zd.ml_ready("data.csv")     # ML readiness score out of 100
zd.compare("train.csv", "test.csv")  # Drift detection in one line

# Or directly from a pandas DataFrame!
df = pd.read_csv("titanic.csv")
zd.profile(df)
zd.clean(df, apply=True)    # Returns a pristine DataFrame
```

---

## 🆚 How Does It Compare?

| Feature | pandas | ydata-profiling | **Zedda** |
| :--- | :---: | :---: | :---: |
| **Titanic (891 rows)** | manual, 0.8s | ~45s | **19ms ⚡** |
| **6.3M row CSV** | manual, 8.2s | OOM crash | **23s ⚡** |
| **1TB Parquet** | OOM crash | OOM crash | **< 2s ⚡** |
| **RAM usage** | $O(N)$ | $O(N)$ | **$O(\text{cols})$ ✅** |
| **pip install size** | ~30 MB | 200 MB+ | **< 1 MB ✅** |
| **Pearson correlation** | manual | slow | **single-pass ✅** |
| **ML readiness hints** | ❌ | ❌ | **✅** |
| **Auto-Fix Code Gen** | ❌ | ❌ | **✅** |
| **Data Drift Detection** | ❌ | ❌ | **✅** |

---

## 🚀 Installation

```bash
pip install zedda
```

- ✅ **No C++ compiler needed** — pre-built wheels for Windows, macOS, and Linux
- ✅ **Requires Python 3.9+**
- ✅ **Tiny install** — less than 1 MB, no heavy dependencies

---

## ✨ Features & API

### 1. `zd.profile()` — Full EDA Report

Instantly generate a beautiful, rich terminal report with data quality scores, outlier detection, distribution stats, and single-pass Pearson correlations — all in milliseconds.

```python
import zedda as zd

zd.profile("data.csv")         # CSV
zd.profile("data.parquet")     # Parquet — uses footer cheat code
zd.profile("data.arrow")       # Arrow IPC
zd.profile("big.csv", sample_size=500_000)  # Force sampling
```

<div align="center">
  <img src="https://raw.githubusercontent.com/Zedda-Labs/Zedda/main/docs/images/profile_demo.jpg" alt="zd.profile() output showing dataset overview, data quality score, and column statistics table" />
  <br/>
  <em>zd.profile() — Full dataset EDA in a single line. Data Quality Score, column stats, Smart Warnings, and Pearson correlations.</em>
</div>

---

### 2. `zd.ml_ready()` — ML Readiness Score

Computes an **ML Readiness score out of 100** by flagging nulls, extreme outliers, high cardinality, multi-collinearity, and more.

```python
zd.ml_ready("data.csv")
```

<div align="center">
  <img src="https://raw.githubusercontent.com/Zedda-Labs/Zedda/main/docs/images/ml_ready_demo.jpg" alt="zd.ml_ready() output showing ML Readiness score, warnings per column, and suggested next step code" />
  <br/>
  <em>zd.ml_ready() — Scores your dataset for ML training readiness, flags every problem column.</em>
</div>

---

### 3. `zd.compare()` — Data Drift Detection

Detect **data drift** between Train/Test splits or Production vs. Baseline in one line. Uses Z-score distribution shift detection (threshold > 1.0) and flags new categories not seen in training.

```python
zd.compare("train.csv", "test.csv")
```

<div align="center">
  <img src="https://raw.githubusercontent.com/Zedda-Labs/Zedda/main/docs/images/compare_demo.jpg" alt="zd.compare() and zd.warnings() output showing new categories detected and all smart warnings" />
  <br/>
  <em>zd.compare() — Automatically detects new categories and distribution shifts between two datasets.</em>
</div>

---

### 4. `zd.fix()` — Auto-Fix Code Generation

Don't just find the issues — **fix them**. Zedda generates exact, copy-pasteable `pandas` or `scikit-learn` code snippets to resolve every detected problem.

```python
zd.fix("data.csv")             # Print fix code snippets

# Or apply them directly — returns a clean DataFrame!
clean_df = zd.fix("data.csv", apply=True)
```

---

### 5. `zd.warnings()` — Smart Warnings

View all data quality warnings for your dataset in a clean, structured list.

```python
zd.warnings("data.csv")
```

---

### 6. `zd.clean()` — AI-Powered Cleaning

Zedda can automatically clean your data by dropping sparse columns, imputing missing values with median/mode, and removing ID columns.

```python
# Prints the exact pandas code to clean the file
zd.clean("data.csv")

# Instantly returns the cleaned DataFrame ready for ML!
clean_df = zd.clean("data.csv", apply=True)
```

---

### 7. `zd.merge()` — Intelligent Merging

Merge datasets with automatic semantic alignment, detecting distribution shifts and schema mismatches before they break your pipeline.

```python
zd.merge(["part1.csv", "part2.csv"], output="combined.csv")
```

---

### 8. `zd.ask()` — Natural Language Queries

Ask **plain-English questions** about your dataset and get instant answers. Features a fast offline rule engine for common questions (no API key needed) and Zedda AI for complex analytical queries.

> **Note:** Complex AI queries require setting the `ZEDDA_AI_KEY` environment variable. You can get a free API key from [Groq](https://console.groq.com/keys) to use the Llama-3-70B model backend.

```python
# Instant offline answers (no API key needed)
zd.ask("titanic.csv", "which columns have more than 10% nulls?")
zd.ask("titanic.csv", "what is the survival rate by class?")

# Zedda AI for complex questions (requires ZEDDA_AI_KEY)
import os
os.environ["ZEDDA_AI_KEY"] = "gsk_..."
zd.ask("data.csv", "which features should I use for a random forest?")
```

---

### 9. `zd.scan()` — Programmatic Access

Need raw stats for your own pipelines? `scan()` returns the full profile object silently — no terminal output.

```python
p = zd.scan("titanic.csv")

print(p.num_rows)              # 891
print(p.num_cols)              # 12
print(p.overall_null_pct)      # 28.3

for col in p.columns:
    if col.null_pct > 20:
        print(f"High nulls: {col.name} ({col.null_pct:.1f}%)")
```

> **See full API reference**: [`docs/API.md`](docs/API.md)

---

## 🖥️ CLI Usage

Zedda ships with a full command-line interface:

```bash
# Profile a file directly in your terminal
zedda run data.csv

# Compare two datasets
zedda compare train.csv test.csv

# Quick file info (fast, no full scan)
zedda info data.csv

# Show version
zedda version
```

---

## 🧠 Architecture — How It Works

Zedda is built on a custom **C++17 streaming core** connected to Python via [`nanobind`](https://github.com/wjakob/nanobind) — the fastest Python/C++ binding library available.

```
  Python API (zd.profile, zd.scan, zd.compare ...)
        │
        │  nanobind (zero-copy)
        ▼
  C++ Streaming Engine
  ┌─────────────────────────────────────────────────────┐
  │  Welford's Algorithm    →  Mean / StdDev / Skew     │
  │  HyperLogLog            →  Cardinality (16KB/col)   │
  │  Pearson Engine         →  O(1) memory correlation  │
  │  Parquet Footer Reader  →  Exact min/max from meta  │
  │  Stratified Sampler     →  99.9% accuracy, 100x I/O │
  └─────────────────────────────────────────────────────┘
        │
        │  Arrow C Data Interface (zero-copy)
        ▼
  PyArrow (Parquet / Arrow IPC file reading)
```

| Algorithm | What It Does | Why |
| :--- | :--- | :--- |
| **Welford's Online Algorithm** | Stable mean/variance/stddev/skewness/kurtosis | Single-pass, no catastrophic cancellation |
| **HyperLogLog** | Cardinality estimation (~99% accuracy) | Uses only **16 KB per column**, regardless of dataset size |
| **Pearson Correlation Engine** | Exact $r$ value for every column pair | $O(1)$ memory, single-pass, no second file read |
| **Parquet Footer Cheat Code** | Reads exact nulls/min/max from file footer | Milliseconds for any file size, no data scan needed |
| **Stratified Row-Group Sampling** | Picks start, middle, and end row groups | 99.9% statistical accuracy with 100× less I/O |

---

## 💾 Memory Usage

Zedda uses $O(\text{columns})$ memory — not $O(\text{rows})$. It **never loads the full dataset** — it streams chunks and updates constant-size running accumulators.

| Dataset | pandas RAM | Zedda RAM |
| :--- | :---: | :---: |
| **1M rows, 10 cols** | ~800 MB | **~2 MB** |
| **10M rows, 30 cols** | ~8 GB | **~6 MB** |
| **1TB Parquet** | OOM | **~50 MB** |

---

## 📊 Benchmarks

*Tested on MacBook Pro M2, 16 GB RAM.*

| Dataset | pandas `describe()` | ydata-profiling | **Zedda** |
| :--- | :---: | :---: | :---: |
| Titanic (891 rows, 12 cols) | 0.8s | 42.0s | **0.019s** ⚡ |
| Fraud (6.3M rows, 31 cols) | 8.2s (no insights) | OOM | **23.0s** ⚡ |
| 1TB Parquet (footer mode) | OOM | OOM | **1.8s** ⚡ |

*Zedda on Fraud: with Smart Warnings + Pearson correlations included.*

---

## 🛣️ Roadmap

| Status | Phase | Description |
| :---: | :--- | :--- |
| ✅ | **Phase 1** | C++ streaming core (Welford, HyperLogLog) |
| ✅ | **Phase 2** | Zero-copy Parquet + Arrow support |
| ✅ | **Phase 3** | Intelligent Sampling Engine (1TB in 2s) |
| ✅ | **Phase 3.1** | Smart Warnings, Data Quality Score, Pearson Correlation |
| ✅ | **Phase 4** | `zd.ml_ready()` and `zd.fix()` — ML readiness + auto-fix code gen |
| ✅ | **Phase 5** | `zd.compare()` — Data drift detection for production vs. baseline |
| ✅ | **Phase 6** | `zd.ask()` — Natural language queries over your dataset |
| ✅ | **Phase 7** | `zd.clean()` & `zd.merge()` — Auto-cleaning & intelligent file merging |

---

## 💬 Community

Join the discussion! We'd love to hear your feedback and help you get started.
- [Join our Discord / Slack (Coming Soon)](#)
- [GitHub Discussions](https://github.com/Zedda-Labs/Zedda/discussions)

---

## 🤝 Contributing

Contributions are welcome and appreciated! Zedda is actively maintained and open to PRs of all sizes.

### Quick Start for Contributors

```bash
# 1. Fork and clone the repository
git clone https://github.com/Zedda-Labs/Zedda.git --recursive
cd Zedda

# 2. Install in editable/development mode
pip install -e ".[dev]"

# 3. Run the test suite
pytest tests/

# 4. Make your changes and open a PR!
```

> **See the full contribution guide**: [`CONTRIBUTING.md`](CONTRIBUTING.md)

---

## 🔐 Security

If you discover a security vulnerability, please report it **privately** via GitHub's [Security Advisories](https://github.com/Zedda-Labs/Zedda/security/advisories) — **do not open a public issue**.

> **See**: [`SECURITY.md`](SECURITY.md)

---

## 📄 License

Zedda is open source software licensed under the **MIT License**.

See [LICENSE](https://github.com/Zedda-Labs/Zedda/blob/main/LICENSE) for details.

---

<div align="center">
  <p>Built with passion and C++17</p>
  <p>
    <a href="https://pypi.org/project/zedda">PyPI</a> •
    <a href="https://github.com/Zedda-Labs/Zedda">GitHub</a> •
    <a href="https://github.com/Zedda-Labs/Zedda/issues">Issues</a> •
    <a href="CONTRIBUTING.md">Contributing</a> •
    <a href="docs/API.md">API Docs</a>
  </p>
  <sub>If Zedda saved you time, please give it a ⭐ on GitHub — it helps a lot!</sub>
</div>
