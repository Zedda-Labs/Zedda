# Zedda API Reference

This document covers the public Python API of Zedda.

## Core Functions

### `zd.profile(path: str | pd.DataFrame, sample_size: int = None) -> None`

Scans a dataset and prints a comprehensive EDA report to the terminal.

* **Arguments:**
  * `path` (str | pd.DataFrame): Path to a `.csv`, `.parquet`, or `.arrow` file, or a pandas DataFrame.
  * `sample_size` (int, optional): Maximum number of rows to sample. If not provided, Zedda auto-samples files larger than 1GB.
* **Returns:** 
  * `None`. The report is printed to the terminal. Use `zd.scan()` for programmatic access.

---

### `zd.scan(path: str | pd.DataFrame, sample_size: int = None, allowed_dir: str = None) -> DatasetProfile`

The programmatic equivalent of `zd.profile()`. Scans the dataset but **does not print anything**. Use this when building pipelines.

* **Arguments:**
  * `path` (str | pd.DataFrame): Path to the dataset, or a pandas DataFrame.
  * `sample_size` (int, optional): Maximum rows to sample.
  * `allowed_dir` (str, optional): Restrict scanning to a specific directory (useful for server/API environments to prevent path traversal).
* **Returns:**
  * A `DatasetProfile` object.

---

### `zd.compare(path_a: str | pd.DataFrame, path_b: str | pd.DataFrame, sample_size: int = None) -> None`

Compares two datasets side-by-side to detect data drift, schema changes, and new categories.

* **Arguments:**
  * `path_a` (str | pd.DataFrame): Path to the baseline/training dataset, or a DataFrame.
  * `path_b` (str | pd.DataFrame): Path to the production/test dataset, or a DataFrame.
  * `sample_size` (int, optional): Max rows to read per file.

---

### `zd.ml_ready(path: str) -> None`

Analyzes a dataset and provides an ML Readiness Score (0-100), flagging issues that will negatively impact machine learning models.

* **Arguments:**
  * `path` (str): Path to the dataset.

---

### `zd.clean(path: str | pd.DataFrame, output: str = None, sample_size: int = None) -> pd.DataFrame`

Auto-clean a dataset by applying all auto-fixable data quality warnings. Creates a backup of the original file, applies fixes (impute missing values, drop sparse columns, encode strings), and saves the cleaned file with a JSON audit trail.

* **Arguments:**
  * `path` (str | pd.DataFrame): Path to a `.csv`, `.parquet`, or `.arrow` file, or a pandas DataFrame.
  * `output` (str, optional): Output file path. If `None`, overwrites the original (after creating a backup).
  * `sample_size` (int, optional): Max rows to sample for profiling.
* **Returns:**
  * The cleaned `pandas.DataFrame`.

* **Example:**
  ```python
  zd.clean("titanic.csv", output="titanic_clean.csv")
  zd.clean.undo("titanic.csv")  # restore from backup
  ```

---

### `zd.merge(paths: list[str], output: str = "combined.csv", sample_size: int = None) -> pd.DataFrame`

Intelligently merges multiple datasets. Verifies schemas, checks for data drift between parts, detects duplicates, and optionally writes to output.

* **Arguments:**
  * `paths` (list[str]): List of dataset paths to merge.
  * `output` (str): Output path to save the merged dataset (default: `"combined.csv"`).
  * `sample_size` (int, optional): Max rows to sample per file for profiling.
* **Returns:**
  * The merged `pandas.DataFrame`.

* **Example:**
  ```python
  zd.merge(["jan.csv", "feb.csv", "mar.csv"], output="combined.csv")
  ```

---

### `zd.warnings(path: str | pd.DataFrame) -> None`

Prints a clean, formatted list of every data quality warning found in the dataset.

* **Arguments:**
  * `path` (str | pd.DataFrame): Path to the dataset, or a pandas DataFrame.

---

### `zd.ask(path: str | pd.DataFrame, question: str, print_output: bool = True) -> str`

Ask a plain-English question about the dataset and get an instant answer. Requires `pip install zedda[ai]`.

* **Arguments:**
  * `path` (str | pd.DataFrame): Path to the dataset, or a pandas DataFrame.
  * `question` (str): Your plain-English question.
  * `print_output` (bool, default True): Whether to print the formatted answer to the terminal.
* **Returns:**
  * The answer as a plain string.

---

### `zd.report(data: str | pd.DataFrame, output: str = None) -> str`

Generate a self-contained HTML report for a dataset. The report includes all column statistics, distribution sparklines, correlation heatmap, and data quality scores.

* **Arguments:**
  * `data` (str | pd.DataFrame): Path to the dataset, or a pandas DataFrame.
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

Returned by `zd.scan()`.

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

