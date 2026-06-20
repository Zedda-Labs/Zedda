# Zedda API Reference

This document covers the public Python API of Zedda.

## Core Functions

### `zd.profile(path: str, sample_size: int = None) -> object`

Scans a dataset and prints a comprehensive EDA report to the terminal.

* **Arguments:**
  * `path` (str): Path to a `.csv`, `.parquet`, or `.arrow` file.
  * `sample_size` (int, optional): Maximum number of rows to sample. If not provided, Zedda auto-samples files larger than 1GB.
* **Returns:** 
  * A `DatasetProfile` object (see below).

---

### `zd.scan(path: str, sample_size: int = None, allowed_dir: str = None) -> object`

The programmatic equivalent of `zd.profile()`. Scans the dataset but **does not print anything**. Use this when building pipelines.

* **Arguments:**
  * `path` (str): Path to the dataset.
  * `sample_size` (int, optional): Maximum rows to sample.
  * `allowed_dir` (str, optional): Restrict scanning to a specific directory (useful for server/API environments to prevent path traversal).
* **Returns:**
  * A `DatasetProfile` object.

---

### `zd.compare(path_a: str, path_b: str, sample_size: int = None) -> None`

Compares two datasets side-by-side to detect data drift, schema changes, and new categories.

* **Arguments:**
  * `path_a` (str): Path to the baseline/training dataset.
  * `path_b` (str): Path to the production/test dataset.
  * `sample_size` (int, optional): Max rows to read per file.

---

### `zd.ml_ready(path: str) -> None`

Analyzes a dataset and provides an ML Readiness Score (0-100), flagging issues that will negatively impact machine learning models.

* **Arguments:**
  * `path` (str): Path to the dataset.

---

### `zd.fix(path: str, apply: bool = False)`

Generates exact, copy-pasteable pandas/scikit-learn code snippets to fix all data quality issues found in the dataset.

* **Arguments:**
  * `path` (str): Path to the dataset.
  * `apply` (bool): If `True`, instead of printing the code, it automatically applies the fixes using `pandas` and returns the cleaned `pandas.DataFrame`.

---

### `zd.warnings(path: str) -> None`

Prints a clean, formatted list of every data quality warning found in the dataset.

* **Arguments:**
  * `path` (str): Path to the dataset.

---

### `zd.ask(path: str, question: str, print_output: bool = True) -> str`

Ask a plain-English question about the dataset and get an instant answer.

* **Arguments:**
  * `path` (str): Path to the dataset.
  * `question` (str): Your plain-English question.
  * `print_output` (bool, default True): Whether to print the formatted answer to the terminal.
* **Returns:**
  * The answer as a plain string.

---

## Data Structures

### `DatasetProfile` Object

Returned by `zd.scan()` and `zd.profile()`.

**Attributes:**
* `num_rows` (int): Total rows scanned.
* `num_cols` (int): Total columns.
* `overall_null_pct` (float): Dataset-wide null percentage.
* `scan_time_ms` (float): Time taken to scan in milliseconds.
* `is_sampled` (bool): True if only a sample was read.
* `columns` (List[ColumnProfile]): List of column statistics.
* `correlations` (List[Correlation]): List of highly correlated pairs.

### `ColumnProfile` Object

Contained within `DatasetProfile.columns`.

**Attributes:**
* `name` (str): Column name.
* `type_str` (str): Inferred type (`'int'`, `'float'`, `'str'`, `'bool'`).
* `null_pct` (float): Percentage of missing values.
* `mean` (float): Arithmetic mean (numeric columns).
* `stddev` (float): Standard deviation.
* `val_min` (float): Minimum value.
* `val_max` (float): Maximum value.
* `unique_approx` (int): Approximate distinct value count (HLL).
* `is_constant` (bool): True if all non-null values are identical.

