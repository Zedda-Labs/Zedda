# Zedda User Guide

Welcome to the Zedda User Guide. Here you will find detailed information about usage, features, and troubleshooting.

## FAQ / Troubleshooting

**I'm getting a "cmake failed" error when installing zedda — what do I do?**

This means pip is trying to build a dependency (usually `pyarrow`) from source because no prebuilt wheel exists yet for your exact Python version + OS combination — this is most common right after a new Python version is released, since packages with C++ extensions (like `pyarrow`) typically take a few months to catch up. 

Fixes, in order of preference:
1. If you only need CSV support: `pip install zedda` (without the `[parquet]` extra) — this avoids `pyarrow` entirely.
2. If you need Parquet support: try installing via conda instead, which often has prebuilt binaries before pip does:
   `conda install -c conda-forge pyarrow` then `pip install zedda[parquet]`
3. As a last resort, use a Python version one or two releases older (e.g. 3.12 or 3.13) until the ecosystem catches up.
