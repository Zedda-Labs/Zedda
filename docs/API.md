# Zedda API Reference

This document covers the public Python API of Zedda.

## Core Functions

### `zd.profile(path, sample_size=None) -> DatasetProfile`

Scans a dataset and prints a comprehensive EDA report to the terminal.

* **Arguments:**
  * `path` (str | Path | pd.DataFrame): Path to a `.csv`, `.parquet`, or `.arrow` file, or a pandas/polars DataFrame.
  * `sample_size` (int, optional): Maximum number of rows to sample. If not provided, Zedda auto-samples files larger than 1GB.
* **Returns:**
  * A `DatasetProfile` object (also prints the report to the terminal). Use `zd.scan()` for silent programmatic access.

---

### `zd.scan(path, sample_size=None, allowed_dir=None) -> DatasetProfile`

The programmatic equivalent of `zd.profile()`. Scans the dataset but **does not print anything**. Use this when building pipelines.

* **Arguments:**
  * `path` (str | Path | pd.DataFrame): Path to the dataset, or a pandas/polars DataFrame.
  * `sample_size` (int, optional): Maximum rows to sample.
  * `allowed_dir` (str, optional): Restrict scanning to a specific directory (useful for server/API environments to prevent path traversal).
* **Returns:**
  * A `DatasetProfile` object.

---

### `zd.compare(path_a, path_b, sample_size=None) -> None`

Compares two datasets side-by-side to detect data drift, schema changes, and new categories.

* **Arguments:**
  * `path_a` (str | Path | pd.DataFrame): Path to the baseline/training dataset, or a DataFrame.
  * `path_b` (str | Path | pd.DataFrame): Path to the production/test dataset, or a DataFrame.
  * `sample_size` (int, optional): Max rows to read per file.
* **Returns:**
  * `None` (prints a drift report to the terminal).

---

### `zd.ml_ready(path, sample_size=None) -> None`

Analyzes a dataset and provides an ML Readiness Score (0-100), flagging issues that will negatively impact machine learning models.

* **Arguments:**
  * `path` (str | Path | pd.DataFrame): Path to the dataset, or a DataFrame.
  * `sample_size` (int, optional): Max rows to sample for profiling.
* **Returns:**
  * `None` (prints a readiness report to the terminal).

---

### `zd.fix(path, apply=False, sample_size=None) -> str | pd.DataFrame`

Scan a dataset and generate copy-paste-ready pandas fix code, or apply fixes directly.

* **Arguments:**
  * `path` (str | Path | pd.DataFrame): Path to a `.csv`, `.parquet`, or `.arrow` file, or a DataFrame.
  * `apply` (bool, default False): If `True`, executes fixes and returns a clean `DataFrame` instead of printing code.
  * `sample_size` (int, optional): Max rows to sample for profiling.
* **Returns:**
  * `None` when `apply=False` (prints fix code to terminal).
  * `pandas.DataFrame` when `apply=True`.

---

### `zd.clean(path, output=None, sample_size=None) -> pd.DataFrame`

Auto-clean a dataset by applying all auto-fixable data quality warnings. Creates a backup of the original file, applies fixes (impute missing values, drop sparse columns, encode strings), and saves the cleaned file with a JSON audit trail.

* **Arguments:**
  * `path` (str | Path | pd.DataFrame): Path to a `.csv`, `.parquet`, or `.arrow` file, or a pandas DataFrame.
  * `output` (str, optional): Output file path. If `None` and input is a file, overwrites the original (after creating a backup). If `None` and input is a DataFrame, returns the cleaned DataFrame without writing to disk.
  * `sample_size` (int, optional): Max rows to sample for profiling.
* **Returns:**
  * The cleaned `pandas.DataFrame`.

* **Example:**
  ```python
  zd.clean("titanic.csv", output="titanic_clean.csv")
  zd.clean.undo("titanic.csv")  # restore from backup
  ```

---

### `zd.merge(paths, output="combined.csv", sample_size=None) -> pd.DataFrame`

Intelligently merges multiple datasets. Verifies schemas, checks for data drift between parts, detects duplicates, and optionally writes to output. Files that fail to scan are skipped with a warning (not aborted).

* **Arguments:**
  * `paths` (list[str] | list[Path] | list[pd.DataFrame]): List of dataset paths or DataFrames to merge (at least 2).
  * `output` (str): Output path to save the merged dataset (default: `"combined.csv"`).
  * `sample_size` (int, optional): Max rows to sample per file for profiling.
* **Returns:**
  * The merged `pandas.DataFrame`.

* **Example:**
  ```python
  zd.merge(["jan.csv", "feb.csv", "mar.csv"], output="combined.csv")
  ```

---

### `zd.warnings(path, sample_size=None) -> None`

Prints a clean, formatted list of every data quality warning found in the dataset.

* **Arguments:**
  * `path` (str | Path | pd.DataFrame): Path to the dataset, or a DataFrame.
  * `sample_size` (int, optional): Max rows to sample for profiling.
* **Returns:**
  * `None` (prints a warning report to the terminal).

---

### `zd.ask(path, question, print_output=True) -> str | None`

Ask a plain-English question about the dataset and get an instant answer. Common questions are answered instantly by an offline rule engine — no network call, no API key. More open-ended questions can optionally route to a free LLM (requires `pip install zedda[ai]` and `ZEDDA_AI_KEY` env var).

* **Arguments:**
  * `path` (str | Path | pd.DataFrame): Path to the dataset, or a DataFrame.
  * `question` (str): Your plain-English question.
  * `print_output` (bool, default True): Whether to print the formatted answer to the terminal.
* **Returns:**
  * When `print_output=False`: the answer as a plain string (or error message string on failure).
  * When `print_output=True`: `None` (prints to terminal).

---

### `zd.report(data, output=None) -> str`

Generate a self-contained HTML report for a dataset. The report includes all column statistics, distribution sparklines, correlation heatmap, and data quality scores.

* **Arguments:**
  * `data` (str | Path | pd.DataFrame): Path to the dataset, or a DataFrame.
  * `output` (str, optional): Output file path for the HTML report. If `None`, a default path is generated.
* **Returns:**
  * The file path of the generated HTML report.

* **Example:**
  ```python
  html_path = zd.report("data.csv", output="report.html")
  print(f"Report saved to {html_path}")
  ```

---

## Data Structures

### `DatasetProfile` Object

Returned by `zd.scan()` and `zd.profile()`.

**Attributes:**
* `file_name` (str): Name of the scanned file.
* `file_path` (str): Full path of the scanned file.
* `num_rows` (int): Total rows scanned.
* `num_cols` (int): Total columns.
* `num_numeric` (int): Number of numeric columns.
* `num_string` (int): Number of string columns.
* `overall_null_pct` (float): Dataset-wide null percentage.
* `total_null_cells` (int): Total null cell count.
* `total_cells` (int): Total cell count (rows × cols).
* `scan_time_ms` (float): Time taken to scan in milliseconds.
* `is_sampled` (bool): True if only a sample was read.
* `columns` (List[ColumnProfile]): List of column statistics.
* `correlations` (List[CorrelationResult]): List of highly correlated pairs (|r| ≥ 0.7).

### `ColumnProfile` Object

Contained within `DatasetProfile.columns`.

**Attributes:**
* `name` (str): Column name.
* `type_str` (str): Inferred type (`'int'`, `'float'`, `'str'`, `'bool'`).
* `total_count` (int): Total values (including nulls).
* `null_count` (int): Number of null values.
* `non_null_count` (int): Number of non-null values.
* `null_pct` (float): Percentage of missing values.
* `unique_approx` (int): Approximate distinct value count (HyperLogLog).
* `unique_pct` (float): Percentage of unique values.
* `mean` (float): Arithmetic mean (numeric columns).
* `stddev` (float): Standard deviation.
* `variance` (float): Variance.
* `skewness` (float): Skewness.
* `kurtosis` (float): Kurtosis.
* `val_min` (float): Minimum value.
* `val_max` (float): Maximum value.
* `range` (float): val_max - val_min.
* `min_str_len` (int): Minimum string length (string columns).
* `max_str_len` (int): Maximum string length (string columns).
* `mean_str_len` (float): Mean string length (string columns).
* `has_high_nulls` (bool): True if null_pct > 20%.
* `is_constant` (bool): True if all non-null values are identical.
* `is_high_cardinality` (bool): True if unique_pct is very high.

### `CorrelationResult` Object

Contained within `DatasetProfile.correlations`.

**Attributes:**
* `col_a` (str): First column name.
* `col_b` (str): Second column name.
* `r` (float): Pearson correlation coefficient in [-1, +1].
* `direction` (str): `"positive"` or `"negative"`.
* `strength` (str): `"weak"`, `"moderate"`, `"strong"`, or `"very_strong"`.

### `ZeddaError`

Base exception class for all zedda-specific errors. Catch this to handle
bad paths, unsupported formats, missing dependencies, etc.

```python
try:
    zd.profile("missing.csv")
except zd.ZeddaError as e:
    print(e)
```
