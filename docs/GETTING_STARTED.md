# Zedda — Complete Usage Guide

This guide covers every public function in Zedda with real terminal output,
parameters, and common workflows. For a quick overview, see the
[README](../README.md). For contribution guidelines, see
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Table of Contents

- [Quick Reference](#quick-reference)
- [Installation](#installation)
- [Core Concepts](#core-concepts)
- [Feature Guide](#feature-guide)
  1. [`zd.profile()`](#1-zdprofile)
  2. [`zd.scan()`](#2-zdscan)
  3. [`zd.compare()`](#3-zdcompare)
  4. [`zd.fix()`](#4-zdfix)
  5. [`zd.ask()`](#5-zdask)
  6. [`zd.ml_ready()`](#6-zdml_ready)
  7. [`zd.warnings()`](#7-zdwarnings)
  8. [`zd.clean()`](#8-zdclean)
  9. [`zd.merge()`](#9-zdmerge)
  10. [`zd.report()`](#10-zdreport)
- [Common Workflows](#common-workflows)
- [CLI Reference](#cli-reference)
- [FAQ / Troubleshooting](#faq--troubleshooting)

---

## Quick Reference

| Function | Returns | Modifies files? |
|---|---|:---:|
| `zd.profile(path)` | `DatasetProfile` + prints report | No |
| `zd.scan(path)` | `DatasetProfile`, silent | No |
| `zd.compare(a, b)` | prints drift report | No |
| `zd.fix(path, apply=False)` | code string, or `DataFrame` if `apply=True` | No |
| `zd.ask(path, question)` | answer string | No |
| `zd.ml_ready(path)` | prints readiness report | No |
| `zd.warnings(path)` | prints full warning list | No |
| `zd.clean(path)` | `CleaningReport`, writes output file | **Yes** (with backup) |
| `zd.merge(paths, output)` | writes combined file | **Yes** (creates new file) |
| `zd.report(path, output)` | path to `.html` file | **Yes** (creates new file) |

---

## Installation

```bash
pip install zedda
```

Pre-built wheels for Windows, macOS (Intel + Apple Silicon), and Linux.
No compiler required. Python 3.9+.

```bash
pip install zedda[ai]     # adds OpenAI integration for zd.ask()
```

---

## Core Concepts

**`DatasetProfile`** — the object returned by `scan()` and `profile()`.
Contains dataset-level stats (`num_rows`, `overall_null_pct`, `correlations`)
and a list of per-column `ColumnProfile` objects (`mean`, `null_pct`,
`unique_approx`, etc.).

**Automatic sampling** — files larger than 1GB are automatically sampled
(stratified, ~2M rows) rather than fully scanned. `is_sampled` on the
returned profile tells you whether this happened. Pass
`sample_size=None` to force a full scan regardless of file size.

**DataFrame input** — every function that accepts a file path also accepts
a pandas or polars `DataFrame` directly:

```python
import pandas as pd
df = pd.read_csv("data.csv")
zd.profile(df)   # no temp file, no extra step
```

**`ZeddaError`** — all user-facing errors (bad path, unsupported format,
missing backup) raise this instead of a generic Python exception, so you
can catch Zedda-specific failures cleanly:

```python
try:
    zd.profile("missing.csv")
except zd.ZeddaError as e:
    print(e)
```

---

## Feature Guide

### 1. `zd.profile()`

**What it does:** Runs a full scan and prints a complete EDA report —
dataset overview, data quality score, per-column statistics, smart
warnings, and correlation alerts.

**When to use it:** Your first command on any new dataset.

```python
zd.profile("titanic.csv")
```

```text
zedda
Scanning titanic.csv...  12 ms

╭──── Dataset Overview ─────────────────────────────╮
│ File:  titanic.csv   Rows: 891   Cols: 12         │
│ Nulls: 28.3%  (3,024 cells)                       │
╰────────────────────────────────────────────────────╯

Data Quality Score:  76/100  ███████---  FAIR  (3 high-null · 1 outlier)

Column       Type   Nulls  Unique~  Mean   Min   Max   Flags
PassengerId  int    0.0%   891      446    1     891   HIGH CARD
Age          float  19.9%  88       29.70  0.42  80    ok
Cabin        str    77.1%  147      len~4  -     -     HIGH NULL

Smart Warnings:
  ✗  'Cabin' — 77.1% nulls, consider dropping
  ⚠  'Age' — 19.9% nulls, needs imputation
  ℹ  'PassengerId' — 100% unique, looks like an ID column

Pearson Correlation Alerts:
  ↑↑ r=+0.83  'SibSp' ↔ 'Parch'  Review before feature selection.
```

**Parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `path` | `str \| Path \| DataFrame` | required | File path or in-memory DataFrame |
| `sample_size` | `int \| None` | `None` (auto) | Force a specific sample size, or `None` for auto/full |

**See also:** [`zd.scan()`](#2-zdscan) for silent access to the same data, [`zd.warnings()`](#7-zdwarnings) for the full (untruncated) warning list.

[↑ Back to top](#table-of-contents)

---

### 2. `zd.scan()`

**What it does:** Identical analysis to `profile()`, but silent — no
terminal output. Returns a structured object for use in scripts,
pipelines, and CI checks.

**When to use it:** Anywhere you need the numbers programmatically rather
than a printed report.

```python
p = zd.scan("titanic.csv")
print(p)
```

```text
DatasetProfile 'titanic.csv'
──────────────────────────────────────────
  rows    : 891
  cols    : 12  (7 numeric · 5 string)
  nulls   : 28.3%  (3,024 cells · Cabin=687, Age=177, Embarked=2)
  scanned : 12 ms  ·  sampled: False
──────────────────────────────────────────
  p.num_rows         →  891
  p.overall_null_pct →  28.3
  p.correlations     →  1 pairs  (|r| ≥ 0.7)
                      SibSp ↔ Parch  r=+0.83  STRONG
──────────────────────────────────────────
  p.columns[5]  →  Age  float  null=19.9%  mean=29.70
                ·  · · · 8 more columns
```

```python
# Use it in a CI data-quality gate:
p = zd.scan("incoming_batch.csv")
if p.overall_null_pct > 10:
    raise SystemExit("Data quality check failed: nulls too high")
```

**Parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `path` | `str \| Path \| DataFrame` | required | File path or in-memory DataFrame |
| `sample_size` | `int \| None` | `None` (auto) | Force a specific sample size, or `None` for full scan |
| `allowed_dir` | `str \| None` | `None` | Restrict reads to this directory (for multi-tenant / server use) |

**See also:** [`zd.profile()`](#1-zdprofile) for the same data with a printed report.

[↑ Back to top](#table-of-contents)

---

### 3. `zd.compare()`

**What it does:** Compares two datasets — schema, null rates, and
distribution shift — and gives a verdict on whether it's safe to train
a model on the second dataset relative to the first.

**When to use it:** Before retraining on new data, or validating that a
test set matches your training set's structure.

```python
zd.compare("train.csv", "test.csv")
```

```text
zedda  ·  compare mode

  A : train.csv  891 rows · 12 cols
  B : test.csv   418 rows · 11 cols

Schema
  ⚠  'Survived' missing in test.csv
     Note: expected for ML train/test splits — target column
     is typically absent from test data.
  ✓  Types: 11/11 match

Distribution Shift
  ✓  'Age'   mean 29.7 → 30.2   stable
  ⚠  'Fare'  mean 32.2 → 35.6   SHIFT (+10%)

Verdict
  ⚠  REVIEW  —  1 expected schema diff · 1 distribution shift
  Safe to train : REVIEW  (check Fare shift before proceeding)
```

A missing column that looks like a binary/categorical target is
downgraded to a warning with an explanation, rather than an automatic
fail — a genuinely missing feature column still produces `FAIL`.

**Parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `path_a` | `str \| Path \| DataFrame` | required | Baseline dataset (e.g. training data) |
| `path_b` | `str \| Path \| DataFrame` | required | Comparison dataset (e.g. test or live data) |
| `sample_size` | `int \| None` | `None` (auto) | Sampling override for either large input |

**See also:** [`zd.merge()`](#9-zdmerge) for combining multiple compatible files instead of comparing two.

[↑ Back to top](#table-of-contents)

---

### 4. `zd.fix()`

**What it does:** Generates exact, copy-pasteable pandas code to resolve
every detected issue — null imputation, outlier transforms, ID-column
drops, high-cardinality encoding. With `apply=True`, executes the fixes
and returns a cleaned `DataFrame` directly.

**When to use it:** When you want the fix code to review or paste into
your own notebook, rather than a fully automated file-level clean.

```python
zd.fix("titanic.csv")
```

```text
zedda  ·  fix mode

3 issues found across 12 columns.

MISSING VALUES
  Age    → 19.9% nulls → fillna(median)
  Cabin  → 77.1% nulls → too sparse to impute → drop

ID COLUMNS
  PassengerId → 100% unique → drop

Copy-Paste Block:
import pandas as pd
  df['Age'] = df['Age'].fillna(df['Age'].median())  # 19.9% nulls
  df = df.drop(columns=['Cabin'])  # 77.1% nulls — too sparse to impute
  df = df.drop(columns=['PassengerId'])  # 100% unique — ID column
```

```python
# Apply directly and get a DataFrame back:
clean_df = zd.fix("titanic.csv", apply=True)
```

Columns above ~50% nulls are dropped rather than imputed — filling most
of a column with one guessed value does more harm than good.

**Parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `path` | `str \| Path \| DataFrame` | required | File path or in-memory DataFrame |
| `apply` | `bool` | `False` | If `True`, executes fixes and returns a `DataFrame` instead of printing code |

**See also:** [`zd.clean()`](#8-zdclean) to apply the same fixes directly to a file, with a backup and undo.

[↑ Back to top](#table-of-contents)

---

### 5. `zd.ask()`

**What it does:** Answers plain-English questions about a dataset. Common
questions are answered instantly by an offline rule engine — no network
call, no API key. More open-ended questions can optionally route to a
free LLM.

**When to use it:** Quick exploratory questions without writing pandas
code yourself.

```python
zd.ask("titanic.csv", "what is the average fare by class?")
```

```text
zedda  ·  ask mode  ·  offline

  Question : what is the average fare by class?
  ──────────────────────────────────────────
  Mean 'Fare' by 'Pclass':
    1    84.15
    2    20.66
    3    13.68

  'Pclass' appears to be a useful feature for predicting 'Fare'.
  ──────────────────────────────────────────
  Mode: offline rule engine · 20 ms
```

```python
# Complex questions fall back to a free LLM if configured:
# export GROQ_API_KEY=...
zd.ask("data.csv", "which features should I drop before training a random forest?")
```

**Parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `path` | `str \| Path \| DataFrame` | required | File path or in-memory DataFrame |
| `question` | `str` | required | Your question, in plain English |
| `print_output` | `bool` | `True` | Set `False` to suppress printing and just capture the return value |

**See also:** [`zd.ml_ready()`](#6-zdml_ready) for a structured (non-conversational) readiness check.

[↑ Back to top](#table-of-contents)

---

### 6. `zd.ml_ready()`

**What it does:** Scores a dataset's readiness for ML training (0–100)
and lists exactly what to fix, with inline code, grouped into "Issues
Found" and "Looks Good".

**When to use it:** Right before you build a training pipeline, to catch
leakage-prone ID columns, sparse features, and multicollinearity early.

```python
zd.ml_ready("titanic.csv")
```

```text
zedda  ·  ml_ready mode

ML Readiness Score:  70/100  ███████---  FAIR

Issues Found
  ✗  Cabin — 77.1% nulls, too sparse to trust imputation
     df = df.drop(columns=['Cabin'])
  ⚠  PassengerId — 891 unique values (ID-like)
     df = df.drop(columns=['PassengerId'])
  ✗  Age — 19.9% nulls
     df['Age'] = df['Age'].fillna(df['Age'].median())

Looks Good
  ✓  Survived — binary (0/1), good ML target
  ✓  Pclass — 3 unique values, good categorical feature

Recommended feature count: 10 of 12 columns
Re-run zd.ml_ready() after fixing to verify score improves.
```

**Parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `path` | `str \| Path \| DataFrame` | required | File path or in-memory DataFrame |
| `sample_size` | `int \| None` | `None` (auto) | Sampling override for large files |

**See also:** [`zd.fix()`](#4-zdfix) to generate the actual fix code shown here.

[↑ Back to top](#table-of-contents)

---

### 7. `zd.warnings()`

**What it does:** The complete, untruncated list of data quality issues
(profile() shows only a few), each ranked by severity and paired with an
exact fix.

**When to use it:** When `profile()` shows "...and N more warnings" and
you need the full list with actionable fixes.

```python
zd.warnings("titanic.csv")
```

```text
zedda  ·  warnings mode  ·  intelligence

Found 6 issues · 3 critical · 2 warnings · 1 info

✗ CRITICAL  'Cabin' — 77.1% nulls
   Too sparse to impute reliably.
   → Fix: df = df.drop(columns=['Cabin'])

✗ CRITICAL  'Age' — 19.9% nulls
   → Fix: df['Age'] = df['Age'].fillna(df['Age'].median())

⚠ WARNING   'Ticket' — 681 unique, high cardinality string
   → Fix: df['Ticket'] = pd.Categorical(df['Ticket']).codes

ℹ INFO      'Survived' — binary, good ML target
   → No action needed

Copy-Paste Fix Block:
  df['Age'] = df['Age'].fillna(df['Age'].median())
  df = df.drop(columns=['Cabin', 'PassengerId', 'Name'])
  df['Ticket'] = pd.Categorical(df['Ticket']).codes

Quality score: 76/100 → run zd.clean() to auto-apply fixes
Auto-fixable: 5 of 6 (83%)
```

**Parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `path` | `str \| Path \| DataFrame` | required | File path or in-memory DataFrame |

**See also:** [`zd.clean()`](#8-zdclean) to apply the Copy-Paste Fix Block automatically.

[↑ Back to top](#table-of-contents)

---

### 8. `zd.clean()`

**What it does:** Applies the fixes from `warnings()`/`fix()` directly to
a file — not just suggestions. Always writes a backup first and reports
the before/after quality score. Fully reversible with `zd.clean.undo()`.

**When to use it:** When you want the cleaning done, not just described.

```python
zd.clean("titanic.csv", output="titanic_clean.csv")
```

```text
zedda  ·  clean mode

Before
  Quality score : 76/100  ███████---  FAIR
  Issues found  : 6  (3 critical · 2 warnings · 1 info)

Backup
  ✓  Backup saved → titanic.csv.zedda-backup
     Restore anytime: zd.clean.undo("titanic.csv")

Applying Fixes
  ✓  Age    → median imputed (29.70)      177 cells
  ✓  Cabin  → dropped (77.1% sparse)      col removed
  ✓  PassengerId → dropped (ID-like)      col removed

After
  Quality score : 95/100  █████████-  GOOD  (+19 points)
  Rows : 891 → 891   Cols : 12 → 9  (3 dropped)

Output
  ✓  Clean file  → titanic_clean.csv
  ✓  Audit trail → titanic_cleaning_audit.json
     Time: 1.8s  ·  Backup: titanic.csv.zedda-backup
```

```python
# Made a mistake? Undo instantly:
zd.clean.undo("titanic.csv")
```

A backup is created once, on the first `clean()` call for a file — it is
never overwritten by later calls, so it always represents the true
original.

**Parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `path` | `str \| Path` | required | File to clean (file path only — not DataFrame, since this writes to disk) |
| `output` | `str \| None` | `"{stem}_clean{ext}"` | Where to write the cleaned file |

**See also:** [`zd.warnings()`](#7-zdwarnings) to preview exactly what `clean()` will do before running it.

[↑ Back to top](#table-of-contents)

---

### 9. `zd.merge()`

**What it does:** Combines multiple local CSV/Parquet files that share a
schema into one file — validating column consistency, detecting
duplicate rows across files, and flagging distribution shifts.

**When to use it:** Combining monthly exports, daily batch files, or any
dataset that arrives in multiple parts.

```python
zd.merge(["jan.csv", "feb.csv", "mar.csv"], output="combined.csv")
```

```text
zedda  ·  merge mode  ·  3 files

  ✓ jan.csv  6,200 rows · 12 cols · 0.0% nulls
  ✓ feb.csv  6,100 rows · 12 cols · 0.2% nulls
  ✓ mar.csv  6,150 rows · 12 cols · 0.1% nulls

Schema Check
  ✓  12/12 columns match across all 3 files

Overlap Check
  ⚠  47 duplicate rows found between feb.csv and mar.csv
     Keeping first occurrence, removing from mar.csv.

Distribution Check
  ⚠  'amount' — Mar is +18% above Jan mean, worth investigating

Merging
  ✓  18,450 rows combined (47 duplicates removed)
  ✓  Source column added: 'zedda_source_file'

Output
  ✓  combined.csv saved · 18,450 rows · 13 cols · 51 ms

  Run zd.profile("combined.csv") to profile the merged dataset.
```

ID-like and binary target columns are excluded from the distribution
check — comparing the mean of a sequential ID or a 0/1 target across
files is meaningless and would only produce false alarms.

**Parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `paths` | `list[str]` | required | 2–20 local file paths, same format and schema |
| `output` | `str` | required | Destination path for the combined file |

**See also:** [`zd.compare()`](#3-zdcompare) for a detailed 2-file comparison instead of an N-file merge.

[↑ Back to top](#table-of-contents)

---

### 10. `zd.report()`

**What it does:** Generates a single, self-contained HTML file with the
full EDA report — dataset overview, quality score, column profiles with
inline charts, warnings, and correlations. No external requests; opens
and renders fully offline.

**When to use it:** Sharing results with a teammate, manager, or anyone
without Python installed.

```python
zd.report("titanic.csv", output="titanic_report.html")
```

```text
zedda
Scanning titanic.csv...  12 ms

Building HTML report...
  ✓ Dataset overview
  ✓ Data quality score
  ✓ 12 column profiles + inline histograms
  ✓ 6 smart warnings
  ✓ 1 correlation alert

Report saved  titanic_report.html  (184 KB)
No external requests · opens offline · share via email/Slack
```

**Parameters**

| Param | Type | Default | Description |
|---|---|---|---|
| `path` | `str \| Path \| DataFrame` | required | File path or in-memory DataFrame |
| `output` | `str \| None` | `"{stem}_report.html"` | Destination path for the HTML file |

**See also:** [`zd.profile()`](#1-zdprofile) for the same information in the terminal instead of a file.

[↑ Back to top](#table-of-contents)

---

## Common Workflows

**New dataset, full triage:**

```python
zd.profile("data.csv")           # get the overview
zd.warnings("data.csv")          # see every issue with fixes
zd.clean("data.csv")             # apply fixes safely
zd.report("data_clean.csv")      # share the result
```

**Before retraining a model:**

```python
zd.compare("train.csv", "new_batch.csv")   # check for drift first
zd.ml_ready("new_batch.csv")               # confirm it's ML-ready
```

**Combining recurring exports:**

```python
zd.merge(["jan.csv", "feb.csv", "mar.csv"], output="q1.csv")
zd.profile("q1.csv")
```

[↑ Back to top](#table-of-contents)

---

## CLI Reference

```bash
zedda run data.csv                       # profile from the terminal
zedda compare train.csv test.csv         # drift check
zedda clean data.csv -o clean.csv        # clean with backup + audit
zedda merge jan.csv feb.csv -o all.csv   # multi-file merge
zedda info data.csv                      # instant file metadata, no scan
zedda version                            # print installed version
```

[↑ Back to top](#table-of-contents)

---

## FAQ / Troubleshooting

**Why is my file being sampled instead of fully scanned?**
Files over 1GB are automatically sampled for speed. Pass
`sample_size=None` to force a full scan — this will take longer but
scan every row.

**What does the `HIGH CARD` flag mean?**
The column has a very high proportion of unique values (e.g. names,
IDs, tickets) — usually not useful as a raw ML feature without encoding.

**`zd.clean.undo()` says no backup found — why?**
A backup is only created the first time `clean()` runs on a specific
file. If the backup file (`{filename}.zedda-backup`) was manually
deleted or moved, undo has nothing to restore from.

**Can I use Zedda without pandas installed?**
Core functions (`profile`, `scan`, `warnings`) work on CSV/Parquet/Arrow
without pandas. Functions that manipulate data directly (`fix(apply=True)`,
`clean`, `merge`) require pandas to be installed.

**Does `zd.ask()` send my data anywhere?**
Not by default. The offline rule engine never leaves your machine. Only
if `GROQ_API_KEY` is set, and only for questions the offline engine can't
answer, is a compact summary (not raw data) sent to the LLM.

[↑ Back to top](#table-of-contents)
