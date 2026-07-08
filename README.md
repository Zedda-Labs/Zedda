<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Zedda-Labs/Zedda/main/docs/logo-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/Zedda-Labs/Zedda/main/docs/logo.png">
  <img alt="Zedda" src="https://raw.githubusercontent.com/Zedda-Labs/Zedda/main/docs/logo.png" width="100%">
</picture>

<br>

# Zedda

**Zero Effort Data Analysis**

C++17-powered EDA and data cleaning engine for Python.

<p>
  <a href="https://pypi.org/project/zedda"><img src="https://img.shields.io/pypi/v/zedda.svg?color=1D9E75" alt="PyPI version"></a>
  <a href="https://pypi.org/project/zedda"><img src="https://img.shields.io/pypi/pyversions/zedda.svg" alt="Python versions"></a>
  <a href="https://pepy.tech/project/zedda"><img src="https://static.pepy.tech/badge/zedda" alt="Downloads"></a>
  <a href="https://github.com/Zedda-Labs/Zedda/actions"><img src="https://github.com/Zedda-Labs/Zedda/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="https://securityscorecards.dev/viewer/?uri=github.com/Zedda-Labs/Zedda"><img src="https://api.securityscorecards.dev/projects/github.com/Zedda-Labs/Zedda/badge" alt="OpenSSF Scorecard"></a>
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

```bash
pip install zedda
```

## How to use

```python
import zedda as zd

zd.profile("data.csv")                    # full EDA report
zd.clean("data.csv", output="clean.csv")  # safe, backed-up auto-clean
zd.compare("train.csv", "test.csv")       # drift detection
zd.ask("data.csv", "which columns have nulls?")
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
<a href="docs/API.md">API Docs</a>
</div>