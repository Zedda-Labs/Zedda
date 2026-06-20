# Getting Started with Zedda

Welcome to Zedda! This guide will walk you through your first steps with the world's fastest Exploratory Data Analysis (EDA) library.

## 1. Installation

Install Zedda via pip. It comes with pre-built C++ binaries, so you don't need a compiler.

```bash
pip install zedda
```
*Requires Python 3.9+*

## 2. Your First Profile

Let's assume you have a dataset named `data.csv`. You can run a complete EDA scan with one line of code:

```python
import zedda as zd

zd.profile("data.csv")
```

This will instantly print a beautiful terminal report showing:
1. Dataset overview (rows, columns, scan speed)
2. Data Quality Score
3. Column statistics (nulls, mean, min, max, distinct values)
4. Smart Warnings (e.g., extreme outliers, constant columns)
5. Pearson Correlation alerts

## 3. Working with Big Data (Parquet)

If your dataset is huge (e.g., millions or billions of rows), you should use Parquet. Zedda has a "cheat code" for Parquet files: it reads the file metadata (footer) to get exact min, max, and null counts in milliseconds, bypassing the need to read the whole file!

```python
zd.profile("huge_data.parquet")
```

## 4. Cleaning the Data

If Zedda flags issues (like nulls or outliers), you don't have to figure out how to fix them yourself. Just use `zd.fix()`:

```python
# Print the exact pandas code needed to fix the data
zd.fix("data.csv")
```

Or better yet, let Zedda apply the fixes for you automatically:

```python
# Returns a clean pandas DataFrame!
clean_df = zd.fix("data.csv", apply=True)
```

## 5. Detecting Data Drift

When deploying machine learning models, your production data might drift away from your training data. Catch this instantly with `zd.compare()`:

```python
# Compare Train vs Test, or Baseline vs Production
zd.compare("train.csv", "production_data.csv")
```

This highlights schema changes, new categories, and distribution shifts.

## 6. Command Line Interface

You don't even need to open a Python script. Zedda comes with a fast CLI:

```bash
# Run EDA directly in the terminal
zedda run data.csv

# Quickly get file info (rows, columns, size)
zedda info data.csv
```

## Next Steps

Check out the full [API Reference](API.md) for more advanced usage!
