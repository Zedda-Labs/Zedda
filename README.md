<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Zedda-Labs/Zedda/main/docs/logo-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/Zedda-Labs/Zedda/main/docs/logo.png">
  <img alt="Zedda" src="https://raw.githubusercontent.com/Zedda-Labs/Zedda/main/docs/logo.png" width="100%">
</picture>

<br>

#

**Zero Effort Data Discovery & Analytics**

C++17-powered EDA and data cleaning engine for Python.

<p>
  <a href="https://pypi.org/project/zedda"><img src="https://img.shields.io/pypi/v/zedda.svg?color=1D9E75" alt="PyPI version"></a>
  <a href="https://pypi.org/project/zedda"><img src="https://img.shields.io/pypi/pyversions/zedda.svg" alt="Python versions"></a>
  <a href="https://pepy.tech/project/zedda"><img src="https://static.pepy.tech/badge/zedda" alt="Downloads"></a>
  <a href="https://github.com/Zedda-Labs/Zedda/actions"><img src="https://github.com/Zedda-Labs/Zedda/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/Zedda-Labs/Zedda/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
</p>

<p>
  <a href="docs/GETTING_STARTED.md"><b>Guide</b></a> ·
  <a href="docs/API.md"><b>API reference</b></a> ·
  <a href="docs/ARCHITECTURE.md"><b>How it works</b></a> ·
  <a href="CONTRIBUTING.md"><b>Contributing</b></a> ·
  <a href="SECURITY.md"><b>Security</b></a>
</p>

</div>

---

## What is Zedda

Zedda profiles, cleans, and validates datasets from a single Python call.
Its core is written in C++17 and streams data in constant memory, so it
scales from a 900-row CSV to a terabyte-scale Parquet file without
changing how you use it.

## Installation

```bash
pip install --upgrade pip                  # Ensure pip >= 22.3 for abi3 wheel recognition
pip install zedda                          # CSV only — zero native deps
pip install "zedda[parquet]"               # adds Parquet/Arrow/Feather support
pip install "zedda[clean]"                 # adds fuzzy typo detection
pip install "zedda[ai]"                    # adds AI Q&A (zd.ask with Groq/OpenAI)
pip install "zedda[parquet,clean,ai]"      # everything together
```

**Platform support:**

| Platform | Base install | `[parquet]` extra |
|---|---|---|
| Linux x86_64 (glibc >= 2.17 / musl) | ✅ prebuilt wheel | ✅ prebuilt pyarrow wheel |
| Linux ARM64 (aarch64) | ✅ prebuilt wheel | ✅ prebuilt pyarrow wheel |
| macOS Intel (x86_64) | ✅ prebuilt wheel | ✅ prebuilt pyarrow wheel |
| macOS Apple Silicon (ARM64) | ✅ prebuilt wheel | ✅ prebuilt pyarrow wheel |
| Windows x86_64 | ✅ prebuilt wheel | ✅ prebuilt pyarrow wheel |
| Windows ARM64 | ✅ prebuilt wheel | ⚠️ pyarrow has no win_arm64 wheel — Parquet requires manual build |
| Python 3.13 free-threaded (cp313t) | ⚠️ Not yet supported — use standard Python 3.13 | |

> **conda users:** Zedda is not yet on conda-forge. Install via pip inside your conda environment:
> ```bash
> conda activate myenv
> pip install zedda
> ```

## How to use

```python
import zedda as zd

zd.profile("data.csv")                    # full EDA report in terminal
zd.scan("data.csv")                       # silent scan for CI/CD pipelines
zd.compare("train.csv", "test.csv")       # train/test drift detection
zd.fix("data.csv", apply=True)            # generate or apply pandas fix code
zd.ask("data.csv", "any nulls here?")     # plain-English dataset Q&A
zd.ml_ready("data.csv")                   # readiness score for ML training
zd.warnings("data.csv")                   # list all issues ranked by severity
zd.clean("data.csv", output="clean.csv")  # safe, backed-up auto-clean
zd.merge(["jan.csv", "feb.csv"], "out")   # safely combine multiple files
zd.report("data.csv", output="rep.html")  # export full report to offline HTML
```

Every function also accepts a pandas `DataFrame` directly — a file path is
never required.

```python
import pandas as pd
df = pd.read_csv("data.csv")
zd.profile(df)
```

See the full list of available functions in the [API reference](docs/API.md),
and how the underlying engine works in [How it works](docs/ARCHITECTURE.md).

## Installation from source

```bash
git clone https://github.com/Zedda-Labs/Zedda.git --recursive
cd Zedda
# C++17 build tools (cmake, ninja) are required
pip install cmake ninja
pip install -e ".[dev]"
pytest tests/
```

## Contributing

Issues and pull requests are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

MIT — see [`LICENSE`](LICENSE).

<div align="center">
<br>
<a href="https://pypi.org/project/zedda">PyPI</a> ·
<a href="https://github.com/Zedda-Labs/Zedda">GitHub</a> ·
<a href="https://github.com/Zedda-Labs/Zedda/issues">Issues</a> ·
<a href="docs/GETTING_STARTED.md">Guide</a> ·
<a href="docs/ARCHITECTURE.md">Architecture</a> ·
<a href="docs/API.md">API Docs</a> ·
<a href="CHANGELOG.md">Changelog</a> ·
<a href="RELEASING.md">Releases</a>
</div>
