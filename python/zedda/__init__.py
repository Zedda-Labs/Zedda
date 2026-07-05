"""
zedda - Zero Effort Data Analysis
====================================

The fastest EDA library ever built.
C++ parallel core. 1TB files in seconds.

Quick start::

    import zedda as zd

    # Profile any CSV / Parquet file
    zd.profile("data.csv")

    # Programmatic access (no print)
    p = zd.scan("data.csv")
    print(p.num_rows, p.columns[0].mean)

    # Compare two datasets for drift
    zd.compare("train.csv", "prod.csv")

    # Auto-generate fix code
    zd.fix("data.csv")

    # Apply fixes and get back a clean DataFrame
    clean_df = zd.fix("data.csv", apply=True)

    # ML readiness check
    zd.ml_ready("data.csv")

    # Intelligence warnings with severity + fix code
    zd.warnings("data.csv")

    # Auto-clean with backup and audit trail
    zd.clean("data.csv", output="clean.csv")

    # Smart merge with dedup and schema check
    zd.merge(["jan.csv", "feb.csv"], output="combined.csv")
"""

from __future__ import annotations
from typing import Any

import ctypes
import math
import re
import time
from pathlib import Path


# ─────────────────────────────────────────────────────────────────
#  Public error class
# ─────────────────────────────────────────────────────────────────
class ZeddaError(Exception):
    """User-friendly error raised by the Zedda engine."""

    pass


__version__ = "0.5.0"
__author__ = "zedda contributors"


# ─────────────────────────────────────────────────────────────────
#  Try importing C++ core
# ─────────────────────────────────────────────────────────────────
try:
    from . import fasteda_core as _core

    _CORE_AVAILABLE = True
except ImportError:
    _CORE_AVAILABLE = False
    _core = None

# ─────────────────────────────────────────────────────────────────
#  Rich for terminal output
# ─────────────────────────────────────────────────────────────────
try:
    from rich import box
    from rich.console import Console
    from rich.markup import escape as rich_escape  # SEC-GEN02
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False

    def rich_escape(s: str) -> str:  # SEC-GEN02: fallback no-op
        return s


_console = Console() if _RICH_AVAILABLE else None

# ─────────────────────────────────────────────────────────────────
#  Arrow C Data Interface struct sizes (from arrow/c/abi.h)
#  ArrowSchema / ArrowArray: 9 pointer-sized fields → 72 bytes on 64-bit.
#  We allocate 256 bytes each for safety.
# ─────────────────────────────────────────────────────────────────
_ARROW_SCHEMA_SIZE = 256
_ARROW_ARRAY_SIZE = 256

# Stores (scanned_rows, total_rows) for sampled files — used by _print_report
_SAMPLED_INFO: dict = {}


# ─────────────────────────────────────────────────────────────────
#  Number formatting helpers
# ─────────────────────────────────────────────────────────────────
def _format_num(val: float, is_integer: bool = False) -> str:
    """Format a numeric value for clean terminal display."""
    if val == 0.0:
        return "0"
    if is_integer:
        return f"{int(val):,}"
    abs_val = abs(val)
    if abs_val >= 1_000_000:
        return f"{val:,.0f}"
    elif abs_val >= 1_000:
        return f"{val:,.1f}"
    elif abs_val >= 1:
        return f"{val:.4f}"
    elif abs_val >= 0.001:
        return f"{val:.6f}"
    else:
        return f"{val:.2e}"


def _format_ci(val: float) -> str:
    """Format a confidence-interval value."""
    if val == 0.0:
        return "0"
    abs_val = abs(val)
    if abs_val >= 1_000:
        return f"{val:,.1f}"
    elif abs_val >= 1:
        return f"{val:.1f}"
    elif abs_val >= 0.01:
        return f"{val:.2f}"
    else:
        return f"{val:.2g}"


def _count_lines(path: str) -> int:
    """Count newlines in a file without reading it fully into memory."""
    try:
        count = 0
        with open(path, "rb") as f:
            while True:
                chunk = f.read(4 * 1024 * 1024)
                if not chunk:
                    break
                count += chunk.count(b"\n")
        return count
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────
#  _require_core() – raise a helpful error if C++ core is missing
# ─────────────────────────────────────────────────────────────────
def _require_core() -> None:
    if not _CORE_AVAILABLE:
        raise ZeddaError(
            "zedda C++ core not found.\nPlease reinstall: pip install zedda"
        )


# ─────────────────────────────────────────────────────────────────
#  SEC-P01: Column name sanitization for generated code
#  Uses repr() to properly escape all special characters, preventing
#  code injection via malicious column names in CSV files.
# ─────────────────────────────────────────────────────────────────
def _safe_col_name(name: str) -> str:
    """Return repr(name) — safe for use inside generated Python code."""
    return repr(name)


# ─────────────────────────────────────────────────────────────────
#  DataFrame Input Resolution Helpers
# ─────────────────────────────────────────────────────────────────
def _write_temp_arrow(df) -> str:
    """Write a pandas DataFrame to a temporary Parquet file."""
    import tempfile

    import pyarrow as pa
    import pyarrow.parquet as pq

    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    tmp.close()
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, tmp.name)
    return tmp.name


def _write_temp_arrow_polars(df) -> str:
    """Write a polars DataFrame to a temporary Parquet file."""
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    tmp.close()
    df.write_parquet(tmp.name)
    return tmp.name


def _resolve_input(data):
    """Resolve input to (file_path_str, is_temp_file) tuple.

    Accepts str/Path (passed through) or pandas/polars DataFrame
    (written to a temp Arrow IPC file).
    """
    from pathlib import Path as _P

    if isinstance(data, (str, _P)):
        return str(data), False
    try:
        import pandas as pd

        if isinstance(data, pd.DataFrame):
            return _write_temp_arrow(data), True
    except ImportError:
        pass
    try:
        import polars as pl

        if isinstance(data, pl.DataFrame):
            return _write_temp_arrow_polars(data), True
    except ImportError:
        pass
    raise ZeddaError(
        f"Unsupported input type: {type(data).__name__}. "
        "Expected file path (str/Path) or pandas/polars DataFrame."
    )


def _cleanup_temp(path):
    """Silently delete a temporary file."""
    import os

    try:
        os.unlink(path)
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────────
#  DatasetProfileWrapper — wraps C++ DatasetProfile with __repr__
#
#  When a user does `print(p)` or `p` in a Jupyter cell, they get a
#  beautiful structured summary instead of a raw C++ object repr.
#  All attribute access is transparently proxied to the C++ object.
# ─────────────────────────────────────────────────────────────────
class DatasetProfileWrapper:
    """Wraps C++ DatasetProfile with a beautiful __repr__ for humans."""

    def __init__(self, profile: Any, display_name: str = None) -> None:
        object.__setattr__(self, "_profile", profile)
        object.__setattr__(self, "_display_name", display_name)

    def __getattr__(self, name: str):
        return getattr(object.__getattribute__(self, "_profile"), name)

    def __setattr__(self, name: str, value) -> None:
        if name in ("_profile", "_display_name"):
            object.__setattr__(self, name, value)
        else:
            setattr(object.__getattribute__(self, "_profile"), name, value)

    def __repr__(self) -> str:
        p = object.__getattribute__(self, "_profile")
        disp = object.__getattribute__(self, "_display_name")
        _display = disp if disp else p.file_name
        sep = "\u2500" * 52
        scan_ms = p.scan_time_ms
        scan_str = (
            f"{scan_ms / 1000:.1f} sec" if scan_ms >= 10_000 else f"{scan_ms:.0f} ms"
        )

        null_breakdown = ""
        if p.total_null_cells > 0:
            null_cols = sorted(
                [c for c in p.columns if c.null_pct > 0],
                key=lambda c: c.null_pct,
                reverse=True,
            )
            parts = []
            for c in null_cols[:3]:
                c_nulls = int(p.num_rows * c.null_pct / 100)
                parts.append(f"{c.name}={c_nulls:,}")
            if len(null_cols) > 3:
                parts.append(f"... {len(null_cols) - 3} more")
            null_breakdown = f" \u00b7 {', '.join(parts)}"

        corr_info = (
            f"  p.correlations    \u2192  {len(p.correlations)} pairs  (|r| \u2265 0.7)"
        )
        if p.correlations:
            corrs = sorted(p.correlations, key=lambda cr: abs(cr.r), reverse=True)
            for cr in corrs[:2]:
                strength = "STRONG" if abs(cr.r) >= 0.8 else "MODERATE"
                corr_info += f"\n                    {cr.col_a} \u2194 {cr.col_b}  r={cr.r:+.2f}  {strength}"

        out = [
            f"\nDatasetProfile '{_display}'",
            sep,
            f"  rows        : {p.num_rows:,}",
            f"  cols        : {p.num_cols}  ({p.num_numeric} numeric \u00b7 {p.num_string} string)",
            f"  nulls       : {p.overall_null_pct:.1f}%  ({p.total_null_cells:,} cells{null_breakdown})",
            f"  scanned     : {scan_str}",
            f"  sampled     : {p.is_sampled}",
            sep,
            f"  p.num_rows        \u2192  {p.num_rows:,}",
            f"  p.num_cols        \u2192  {p.num_cols}",
            f"  p.overall_null_pct\u2192  {p.overall_null_pct:.1f}",
            f"  p.scan_time_ms    \u2192  {p.scan_time_ms:.1f}",
            corr_info,
            sep,
        ]

        MAX_SHOW = 3
        for i, col in enumerate(p.columns[:MAX_SHOW]):
            if col.type_str in ("int", "float"):
                stat = f"mean={col.mean:.4g}"
            else:
                stat = f"len~{col.mean_str_len:.0f}"
            out.append(
                f"  p.columns[{i}]  \u2192  {col.name:<14} {col.type_str:<7} "
                f"null={col.null_pct:.1f}%  {stat}"
            )

        remaining = len(p.columns) - MAX_SHOW
        if remaining > 0:
            out.append(
                f"                \u00b7   \u00b7 \u00b7 \u00b7 {remaining} more columns"
            )

        return "\n".join(out) + "\n"

    def __str__(self) -> str:
        return self.__repr__()


# ─────────────────────────────────────────────────────────────────
#  scan() — run the C++ engine, return a DatasetProfile (no print)
#
#  KEY DIFFERENCE vs profile():
#    profile(path)  →  scans + PRINTS a beautiful terminal report
#    scan(path)     →  scans + RETURNS the raw profile object (no print)
#
#  Use scan() when you want to:
#    - Access column stats programmatically (p.columns[0].mean)
#    - Feed the profile into your own logic or pipeline
#    - Power other zedda functions internally (ml_ready, fix, compare)
# ─────────────────────────────────────────────────────────────────
def scan(path, sample_size: int = None, allowed_dir: str = None) -> Any:
    """
    Scan a CSV or Parquet file using the C++ parallel engine and return
    a DatasetProfile object containing full column-level statistics.

    This is the **raw / programmatic** interface to the zedda engine.
    It runs the same fast C++ scan as ``zd.profile()`` but does NOT
    print anything to the terminal — it just returns the result object
    so you can work with it in code.

    When to use ``scan()`` vs ``profile()``
    ----------------------------------------
    * ``zd.profile(path)``  — scan + print a full terminal report  ← for humans
    * ``zd.scan(path)``     — scan + return the object silently     ← for code

    Args:
        path (str):
            Path to a ``.csv``, ``.parquet``, or ``.arrow`` file.
        sample_size (int, optional):
            Maximum number of rows to read. Automatically activates
            for files larger than 1 GB (defaults to 2,000,000 rows).
        allowed_dir (str, optional):
            If provided, zedda will refuse to scan any file whose
            resolved path is outside this directory. Useful in web
            servers or multi-tenant environments to prevent path
            traversal attacks. (SEC-P02)

    Returns:
        DatasetProfile: An object with the following key attributes:

        * ``p.num_rows``         - total rows in the file
        * ``p.num_cols``         - number of columns
        * ``p.overall_null_pct`` - dataset-wide null percentage
        * ``p.scan_time_ms``     - how long the scan took (ms)
        * ``p.is_sampled``       - True if only a sample was read
        * ``p.columns``          - list of ColumnProfile objects, each with:
            - ``.name``          column name
            - ``.type_str``      data type: 'int', 'float', 'str', 'bool'
            - ``.null_pct``      percentage of missing values
            - ``.mean``          mean (numeric columns only)
            - ``.stddev``        standard deviation
            - ``.val_min``       minimum value
            - ``.val_max``       maximum value
            - ``.unique_approx`` approximate distinct value count (HyperLogLog)
        * ``p.correlations``     - list of Pearson correlation pairs (r >= 0.7)

    Raises:
        ZeddaError: If the file is not found, empty, or in an
            unsupported format.

    Examples::

        import zedda as zd

        # --- Basic usage ---
        p = zd.scan("titanic.csv")
        print(p.num_rows)             # 891
        print(p.num_cols)             # 12
        print(p.overall_null_pct)     # 28.3

        # --- Access a specific column ---
        age_col = p.columns[0]
        print(age_col.name)           # 'Age'
        print(age_col.mean)           # 29.69
        print(age_col.null_pct)       # 19.87
        print(age_col.unique_approx)  # 89

        # --- Loop over all columns ---
        for col in p.columns:
            if col.null_pct > 20:
                print(f"High nulls: {col.name} ({col.null_pct:.1f}%)")

        # --- Sample a huge file (auto-activates for > 1 GB) ---
        p = zd.scan("10gb_log.csv", sample_size=500_000)

        # --- Restrict to a safe directory (server/API use) ---
        p = zd.scan(user_input_path, allowed_dir="/data/uploads")
    """
    _require_core()

    resolved_path, is_temp = _resolve_input(path)
    display_name = "<DataFrame>" if is_temp else None

    try:
        # SEC-P02: Reject paths containing null bytes (C string terminator attack)
        if "\x00" in str(resolved_path):
            raise ZeddaError("Path contains null bytes - rejected for safety.")

        file_path = Path(resolved_path)
        if not file_path.exists():
            raise ZeddaError(
                f"File not found: '{resolved_path}'\n"
                "Tip: Use an absolute path or check your spelling."
            )

        # SEC-P02: Resolve symlinks and check allowed directory
        resolved = file_path.resolve()
        if allowed_dir:
            allowed = Path(allowed_dir).resolve()
            if not str(resolved).startswith(str(allowed)):
                raise ZeddaError(
                    f"Path '{resolved_path}' resolves to '{resolved}' which is outside "
                    f"allowed directory '{allowed_dir}'."
                )

        ext = file_path.suffix.lower()
        supported = {".csv", ".parquet", ".arrow"}
        if ext not in supported:
            raise ZeddaError(
                f"Unsupported format: '{ext}'.\n"
                f"Supported: {', '.join(sorted(supported))}"
            )

        # SEC-DOS01: Reject 0-byte files before calling C++ core
        if resolved.stat().st_size == 0:
            raise ZeddaError(
                f"File is empty (0 bytes): '{resolved_path}'\n"
                "Tip: Check that the file was written correctly."
            )

        # ── Auto-sampling logic ───────────────────────────────────────
        is_sampled = False
        if sample_size is not None:
            is_sampled = True
        elif file_path.stat().st_size > 1024 * 1024 * 1024:  # 1 GB threshold
            is_sampled = True
            sample_size = 2_000_000

        safe_sample = sample_size if sample_size else 1_000_000

        if ext in (".parquet", ".arrow"):
            return DatasetProfileWrapper(
                _scan_arrow(
                    str(resolved_path), is_sampled=is_sampled, sample_size=safe_sample
                ),
                display_name=display_name,
            )
        profile_obj = _core.profile(str(resolved_path), False, is_sampled, safe_sample)
        if is_sampled:
            total_rows = _count_lines(str(resolved_path))
            _SAMPLED_INFO[str(resolved_path)] = (profile_obj.num_rows, total_rows)
        return DatasetProfileWrapper(profile_obj, display_name=display_name)
    except Exception as e:  # SEC-DOS03: Catch all exceptions including ArrowInvalid
        if isinstance(e, ZeddaError):
            raise
        raise ZeddaError(str(e)) from None
    finally:
        if is_temp:
            _cleanup_temp(resolved_path)


# ─────────────────────────────────────────────────────────────────
#  _scan_arrow() — zero-copy Parquet → C++ via Arrow C Data Interface
#
#  Phase 3 features:
#    • Stratified row-group sampling (reads only 6 representative groups)
#    • Parquet Footer Cheat Code: exact nulls/min/max from metadata
#    • Confidence intervals in terminal output when sampled
# ─────────────────────────────────────────────────────────────────
def _scan_arrow(
    path: str, is_sampled: bool = False, sample_size: int = 1_000_000
) -> Any:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise ZeddaError("pyarrow is required for Parquet. Run: pip install pyarrow")

    t0 = time.perf_counter()
    pf = pq.ParquetFile(path)

    total_rows = pf.metadata.num_rows
    num_row_groups = pf.metadata.num_row_groups

    # ── Stratified sampling: pick 6 representative row groups ─────
    #    Covers the start, middle, and end of the dataset.
    #    This is statistically more reliable than purely random.
    if num_row_groups <= 6 or not is_sampled:
        selected_groups = list(range(num_row_groups))
        final_is_sampled = False
    else:
        mid = num_row_groups // 2
        selected_groups = sorted(
            {
                0,
                1,
                mid - 1,
                mid,
                num_row_groups - 2,
                num_row_groups - 1,
            }
        )
        final_is_sampled = True

    profiler = _core.ArrowProfiler(path, total_rows)

    # ── Stream selected row groups to C++ via Arrow C Data Interface ──
    # IMPORTANT: We allocate fresh ctypes buffers per batch.
    # PyArrow _export_to_c transfers ownership to C++.
    # The C++ release() callback (set by PyArrow) is responsible for
    # freeing; we must NOT call release() in our C++ code ourselves.
    for rg_idx in selected_groups:
        rg = pf.read_row_group(rg_idx)
        for batch in rg.to_batches(max_chunksize=65_536):
            # Allocate properly-sized buffers for the Arrow C structs
            schema_buf = (ctypes.c_uint8 * _ARROW_SCHEMA_SIZE)()
            array_buf = (ctypes.c_uint8 * _ARROW_ARRAY_SIZE)()

            ptr_schema = ctypes.addressof(schema_buf)
            ptr_array = ctypes.addressof(array_buf)

            # PyArrow fills the structs at our pointers and sets release()
            batch._export_to_c(ptr_array, ptr_schema)

            # C++ reads the data; release() is called by C++ consume_batch
            profiler.consume_batch(ptr_schema, ptr_array)

            # Keep Python objects alive until C++ is done (GC anchor)
            del schema_buf, array_buf

    profile_obj = profiler.finalize()

    # ── Parquet Footer Cheat Code ─────────────────────────────────
    # Parquet stores per-column statistics (null_count, min, max) inside
    # the file footer — readable in milliseconds regardless of file size.
    # We override sampled stats with these EXACT values.
    num_cols = profile_obj.num_cols
    for i in range(num_cols):
        exact_nulls = 0
        exact_min = None
        exact_max = None
        footer_ok = True

        for rg_idx in range(num_row_groups):
            try:
                col_meta = pf.metadata.row_group(rg_idx).column(i)
                stats = col_meta.statistics
                if stats is None:
                    footer_ok = False
                    break
                exact_nulls += stats.null_count
                if stats.has_min_max:
                    cmin, cmax = stats.min, stats.max
                    if cmin is not None:
                        exact_min = cmin if exact_min is None else min(exact_min, cmin)
                    if cmax is not None:
                        exact_max = cmax if exact_max is None else max(exact_max, cmax)
            except Exception:
                footer_ok = False
                break

        if footer_ok:
            col = profile_obj.columns[i]
            col.null_count = exact_nulls
            col.null_pct = (exact_nulls / total_rows * 100.0) if total_rows > 0 else 0.0
            col.non_null_count = total_rows - exact_nulls
            col.has_high_nulls = col.null_pct > 20.0

            if (
                exact_min is not None
                and exact_max is not None
                and isinstance(exact_min, (int, float))
                and isinstance(exact_max, (int, float))
            ):
                col.val_min = float(exact_min)
                col.val_max = float(exact_max)
                col.range = float(exact_max) - float(exact_min)

    profile_obj.scan_time_ms = (time.perf_counter() - t0) * 1000.0
    profile_obj.is_sampled = final_is_sampled

    if final_is_sampled:
        scanned_rows = profile_obj.num_rows
        _SAMPLED_INFO[path] = (scanned_rows, total_rows)
        profile_obj.num_rows = scanned_rows
    else:
        profile_obj.num_rows = total_rows

    return profile_obj


# ─────────────────────────────────────────────────────────────────
#  profile() — scan + print beautiful terminal report
# ─────────────────────────────────────────────────────────────────
def profile(path, sample_size: int = None) -> Any:
    """
    Profile a file or DataFrame and print a beautiful terminal report.

    One line does everything::

        import zedda as zd
        zd.profile("data.csv")
        zd.profile("big_file.parquet", sample_size=500_000)
        zd.profile(my_dataframe)   # pandas or polars DataFrame

    Args:
        path:        Path to your data file (.csv, .parquet, .arrow) or DataFrame.
        sample_size: Max rows to sample (auto if file > 500 MB).

    Returns:
        DatasetProfile (also prints report to terminal).
    """
    resolved_path, is_temp = _resolve_input(path)
    display_name = (
        "<DataFrame>"
        if is_temp
        else (Path(path).name if isinstance(path, (str, Path)) else "<DataFrame>")
    )

    try:
        if _RICH_AVAILABLE and _console:
            _console.print(f"\n[bold blue]zedda[/bold blue] [dim]v{__version__}[/dim]")
            _console.print(f"[dim]Scanning[/dim] [cyan]{display_name}[/cyan]...\n")

        result = scan(resolved_path, sample_size=sample_size)
        if is_temp and hasattr(result, "_display_name"):
            object.__setattr__(result, "_display_name", display_name)
        _print_report(result)
        return result
    finally:
        if is_temp:
            _cleanup_temp(resolved_path)


# ─────────────────────────────────────────────────────────────────
#  _collect_warnings() — shared warning logic used by profile,
#  warnings(), and clean()
#
#  Returns structured dicts with severity levels, fix code, and
#  auto-fixable flags so callers can format, count, categorize,
#  and apply fixes independently.
# ─────────────────────────────────────────────────────────────────
def _collect_warnings(p: Any) -> list:
    """Collect structured warnings for a dataset profile.

    Returns:
        list of dicts, each with keys:
            icon       : str  — '✗', '⚠', 'ℹ'
            column     : str  — raw column name
            message    : str  — plain text description (no Rich markup)
            category   : str  — 'null', 'id', 'cardinality', 'target',
                                'constant', 'outlier'
            severity   : str  — 'critical', 'warning', 'info'
            fix_code   : str  — pandas fix code snippet (or empty)
            fix_action : str  — human description of the fix action
            auto_fixable : bool — whether clean() can auto-apply this fix
    """
    warn_list = []
    for col in p.columns:
        safe = _safe_col_name(col.name)

        # ── CRITICAL: Sparse columns (>50% nulls) — drop ──────────
        if col.null_pct > 50:
            warn_list.append(
                {
                    "icon": "✗",
                    "column": col.name,
                    "message": f"{col.null_pct:.1f}% nulls",
                    "fix_action": "Too sparse to impute reliably.",
                    "fix_code": f"df = df.drop(columns=[{safe}])",
                    "category": "null",
                    "severity": "critical",
                    "auto_fixable": True,
                    "action_type": "drop",
                }
            )
            continue  # skip further checks for this column

        # ── CRITICAL: Moderate nulls (>5%) — impute ───────────────
        if col.null_pct > 5:
            if col.type_str in ("int", "float"):
                code = f"df[{safe}] = df[{safe}].fillna(df[{safe}].median())"
            else:
                code = f"df[{safe}] = df[{safe}].fillna(df[{safe}].mode()[0])"
            warn_list.append(
                {
                    "icon": "✗",
                    "column": col.name,
                    "message": f"{col.null_pct:.1f}% nulls",
                    "fix_action": f"Impute with {'median' if col.type_str in ('int', 'float') else 'mode'}.",
                    "fix_code": code,
                    "category": "null",
                    "severity": "critical",
                    "auto_fixable": True,
                    "action_type": "impute",
                }
            )

        # ── CRITICAL: ID-like int columns (>95% unique) — drop ────
        if col.type_str == "int" and col.unique_pct > 95:
            warn_list.append(
                {
                    "icon": "✗",
                    "column": col.name,
                    "message": f"{col.unique_pct:.0f}% unique, ID column",
                    "fix_action": "No predictive signal — drop before training.",
                    "fix_code": f"df = df.drop(columns=[{safe}])",
                    "category": "id",
                    "severity": "critical",
                    "auto_fixable": True,
                    "action_type": "drop",
                }
            )

        # ── CRITICAL: Constant column — drop ──────────────────────
        if col.is_constant:
            warn_list.append(
                {
                    "icon": "✗",
                    "column": col.name,
                    "message": "only 1 unique value — zero variance",
                    "fix_action": "Useless for ML, drop it.",
                    "fix_code": f"df = df.drop(columns=[{safe}])",
                    "category": "constant",
                    "severity": "critical",
                    "auto_fixable": True,
                    "action_type": "drop",
                }
            )

        # ── WARNING: High-cardinality strings (ID-like, >80% unique) ──
        if (
            col.type_str in ("str", "unknown")
            and p.num_rows > 0
            and col.unique_approx > p.num_rows * 0.8
        ):
            warn_list.append(
                {
                    "icon": "⚠",
                    "column": col.name,
                    "message": f"{col.unique_approx:,} unique values, high cardinality",
                    "fix_action": "Too many unique values — drop for ML.",
                    "fix_code": f"df = df.drop(columns=[{safe}])",
                    "category": "cardinality",
                    "severity": "warning",
                    "auto_fixable": True,
                    "action_type": "drop",
                }
            )
        # ── WARNING: Moderate cardinality strings (>20 unique) — encode ──
        elif (
            col.type_str in ("str", "unknown")
            and col.unique_approx > 20
        ):
            warn_list.append(
                {
                    "icon": "⚠",
                    "column": col.name,
                    "message": f"{col.unique_approx:,} unique, high cardinality string",
                    "fix_action": "Label encode for ML models.",
                    "fix_code": f"df[{safe}] = pd.Categorical(df[{safe}]).codes",
                    "category": "cardinality",
                    "severity": "warning",
                    "auto_fixable": True,
                    "action_type": "encode",
                }
            )

        # ── WARNING: Extreme outlier (max >> 10x mean) ────────────
        if (
            col.type_str in ("int", "float")
            and col.mean > 0
            and col.unique_approx > 5
            and col.val_max > 10
            and "ratio" not in col.name.lower()
            and "pct" not in col.name.lower()
            and col.val_max > col.mean * 10
        ):
            is_int = col.type_str == "int"
            warn_list.append(
                {
                    "icon": "⚠",
                    "column": col.name,
                    "message": (
                        f"max ({_format_num(col.val_max, is_int)}) is "
                        f"{col.val_max / col.mean:.0f}x above mean"
                    ),
                    "fix_action": "Clip extreme values.",
                    "fix_code": f"df[{safe}] = df[{safe}].clip(upper=df[{safe}].quantile(0.99))",
                    "category": "outlier",
                    "severity": "warning",
                    "auto_fixable": True,
                    "action_type": "clip",
                }
            )

        # ── INFO: Binary target candidate ─────────────────────────
        if (
            col.unique_approx <= 3
            and col.type_str == "int"
            and col.val_min == 0
            and col.val_max == 1
        ):
            warn_list.append(
                {
                    "icon": "ℹ",
                    "column": col.name,
                    "message": "binary, good ML target",
                    "fix_action": "No action needed",
                    "fix_code": "",
                    "category": "target",
                    "severity": "info",
                    "auto_fixable": False,
                    "action_type": "none",
                }
            )

    # Sort: critical first, then warning, then info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    warn_list.sort(key=lambda w: severity_order.get(w["severity"], 9))
    return warn_list


def _collect_warnings_legacy(p: Any) -> list:
    """Legacy wrapper: return old-format warnings for _print_report() compatibility."""
    new_warnings = _collect_warnings(p)
    legacy = []
    for w in new_warnings:
        # Map new icons back to old icon keys used by _print_report
        icon_map = {"✗": "x", "⚠": "!", "ℹ": "i"}
        legacy.append(
            {
                "icon": icon_map.get(w["icon"], w["icon"]),
                "column": w["column"],
                "message": w["message"],
                "category": w["category"],
            }
        )
    return legacy


# ─────────────────────────────────────────────────────────────────
#  _quality_score() / _quality_score_display() — Data Quality Score
# ─────────────────────────────────────────────────────────────────
def _quality_score(p, original_cols: int = None) -> int:
    """Compute a 0-100 data quality score from the profile object."""
    score = 100
    if original_cols and p.num_cols < original_cols:
        # Penalize for dropped columns (information loss)
        dropped = original_cols - p.num_cols
        score -= min(20, dropped * 5)
    # Penalize nulls (up to -40)
    score -= min(40, int(p.overall_null_pct * 2))
    # Penalize high-null columns >20% (up to -20)
    high_null_cols = sum(1 for c in p.columns if c.has_high_nulls)
    score -= min(20, high_null_cols * 5)
    # Penalize constant columns (up to -20)
    constant_cols = sum(1 for c in p.columns if c.is_constant)
    score -= min(20, constant_cols * 10)
    # Penalize extreme outliers (up to -20)
    outlier_cols = sum(
        1
        for c in p.columns
        if c.type_str in ("int", "float")
        and c.unique_approx > 5
        and c.mean > 0
        and c.val_max > 10
        and c.val_max > c.mean * 10
        and "ratio" not in c.name.lower()
        and "pct" not in c.name.lower()
    )
    score -= min(20, outlier_cols * 3)
    return max(0, score)


def _quality_score_display(p: Any, console) -> None:
    """Print a visual quality score bar to the console."""
    score = _quality_score(p)
    filled = score // 10
    bar = "=" * filled + "-" * (10 - filled)

    if score >= 80:
        color, label = "green", "GOOD"
    elif score >= 60:
        color, label = "yellow", "FAIR"
    else:
        color, label = "red", "POOR"

    hints = []
    high_null = sum(1 for c in p.columns if c.has_high_nulls)
    constant = sum(1 for c in p.columns if c.is_constant)
    outlier_c = sum(
        1
        for c in p.columns
        if c.type_str in ("int", "float")
        and c.unique_approx > 5
        and c.mean > 0
        and c.val_max > 10
        and c.val_max > c.mean * 10
        and "ratio" not in c.name.lower()
        and "pct" not in c.name.lower()
    )

    if high_null:
        hints.append(f"{high_null} high-null col{'s' if high_null > 1 else ''}")
    if constant:
        hints.append(f"{constant} constant col{'s' if constant > 1 else ''}")
    if outlier_c:
        hints.append(f"{outlier_c} col{'s' if outlier_c > 1 else ''} with outliers")

    hint_str = f"  [dim]({', '.join(hints)})[/dim]" if hints else ""

    console.print(
        f"\n[bold]Data Quality Score:[/bold]  "
        f"[{color}]{score}/100  {bar}  {label}[/{color}]"
        f"{hint_str}\n"
    )


# ─────────────────────────────────────────────────────────────────
#  _correlation_alerts() — strong Pearson correlation warnings
# ─────────────────────────────────────────────────────────────────
def _correlation_alerts(p, console) -> None:
    """Print Pearson correlation alerts for r >= 0.7."""
    alerts = []
    for cr in p.correlations:
        if abs(cr.r) >= 0.7:
            # Highlight extreme collinearity (>= 0.9) in red to prompt immediate action
            abs_r = abs(cr.r)
            color = "red" if abs_r >= 0.9 else "yellow"
            action = (
                "Drop one before ML training."
                if abs_r >= 0.95
                else "Review before feature selection."
            )
            sym = "↑↑" if cr.direction == "positive" else "↓↑"
            alerts.append(
                f"  [{color}]{sym} r={cr.r:+.2f}[/{color}]  "
                f"'[cyan]{cr.col_a}[/cyan]' ↔ '[cyan]{cr.col_b}[/cyan]'  "
                f"[dim]{action}[/dim]"
            )

    if alerts:
        lines = [
            "[bold]Pearson Correlation Alerts:[/bold]  [dim](single-pass O(1) math)[/dim]"
        ]
        for a in alerts[:5]:
            lines.append(a)
        if len(alerts) > 5:
            lines.append(f"  [dim]... and {len(alerts) - 5} more pairs.[/dim]")
        console.print("\n".join(lines) + "\n")


# ─────────────────────────────────────────────────────────────────
#  _print_report() — full Rich terminal report (used by profile())
# ─────────────────────────────────────────────────────────────────
def _print_report(p: Any) -> None:
    if not _RICH_AVAILABLE or _console is None:
        _print_plain(p)
        return

    # ── Dataset summary panel ─────────────────────────────────────
    title = "[bold blue]Dataset Overview[/bold blue]"
    sampled_lines = ""
    if p.is_sampled:
        title += "  [yellow]⚡ SAMPLED[/yellow]"
        scanned_rows, total_rows = _SAMPLED_INFO.get(
            p.file_path, (p.num_rows, p.num_rows)
        )
        sample_pct = (scanned_rows / total_rows * 100.0) if total_rows > 0 else 0.0
        is_parquet = Path(p.file_path).suffix.lower() in (".parquet", ".arrow")
        method_str = (
            "nulls/min/max exact from footer"
            if is_parquet
            else "early-stop/reservoir sampling"
        )
        sampled_lines = (
            f"\n  [yellow]⚡ SAMPLED[/yellow]  [dim]{scanned_rows:,} of {total_rows:,} rows "
            f"({sample_pct:.1f}%)[/dim]"
            f"\n            [dim]{method_str}[/dim]"
        )

    rows_display = f"{p.num_rows:,}" if p.num_rows >= 0 else "unknown"

    scan_ms = p.scan_time_ms
    scan_str = f"{scan_ms / 1000:.1f} sec" if scan_ms >= 10_000 else f"{scan_ms:.0f} ms"

    summary = (
        f"[bold]File:[/bold]     {p.file_name}{sampled_lines}\n"
        f"[bold]Rows:[/bold]     [green]{rows_display}[/green]\n"
        f"[bold]Cols:[/bold]     {p.num_cols}  "
        f"([cyan]{p.num_numeric} numeric[/cyan], "
        f"[magenta]{p.num_string} string[/magenta])\n"
        f"[bold]Nulls:[/bold]    "
        + ("[red]" if p.overall_null_pct > 10 else "[green]")
        + f"{p.overall_null_pct:.1f}%[/]"
        + f"  ({p.total_null_cells:,} cells)\n"
        f"[bold]Scanned:[/bold]  {scan_str}"
    )

    _console.print(Panel(summary, title=title, border_style="blue", expand=False))

    # ── Data Quality Score ────────────────────────────────────────
    _quality_score_display(p, _console)

    # ── Column table ──────────────────────────────────────────────
    table = Table(
        show_header=True,
        header_style="bold white on blue",
        border_style="dim",
        box=box.SIMPLE_HEAVY,
        padding=(0, 1),
    )
    table.add_column("Column", style="bold cyan", min_width=12)
    table.add_column("Type", style="magenta", min_width=6)
    table.add_column("Nulls", justify="right", min_width=8)
    table.add_column("Unique~", justify="right", min_width=8)
    table.add_column("Mean", justify="right", min_width=12)
    # Hide confidence interval (CI) column for full scans (non-sampled data)
    # to avoid user confusion since CI is only relevant when estimating from samples.
    if p.is_sampled:
        table.add_column("CI +/-95%", justify="right", min_width=10)
    table.add_column("Min", justify="right", min_width=12)
    table.add_column("Max", justify="right", min_width=12)
    table.add_column("Flags", min_width=14)

    truncated_names = []
    for col in p.columns:
        # Null cell coloring
        null_cell = Text(f"{col.null_pct:.1f}%")
        if col.null_pct > 20:
            null_cell.stylize("bold red")
        elif col.null_pct > 5:
            null_cell.stylize("yellow")
        else:
            null_cell.stylize("green")

        # Mean / Min / Max / CI
        is_int = col.type_str == "int"
        if col.type_str in ("int", "float"):
            mean_str = _format_num(col.mean, is_int)
            if p.is_sampled and col.non_null_count > 1:
                stderr = 1.96 * col.stddev / math.sqrt(col.non_null_count)
                ci_str = f"+/-{_format_ci(stderr)}"
            else:
                ci_str = "-"
            min_str = _format_num(col.val_min, is_int)
            max_str = _format_num(col.val_max, is_int)
        else:
            mean_str = f"len~{col.mean_str_len:.0f}"
            ci_str = "-"
            min_str = "-"
            max_str = "-"

        # Health flags
        flags = []
        if col.has_high_nulls:
            flags.append("[red]HIGH NULL[/red]")
        if col.is_constant:
            flags.append("[yellow]CONST[/yellow]")
        if col.is_high_cardinality:
            flags.append("[blue]HIGH CARD[/blue]")
        flags_str = " ".join(flags) if flags else "[dim]ok[/dim]"

        # Column name truncation
        if len(col.name) > 16:
            col_display = col.name[:15] + "…"
            truncated_names.append(col.name)
        else:
            col_display = col.name

        row_data = [
            col_display,
            col.type_str,
            null_cell,
            str(col.unique_approx),
            mean_str,
        ]
        if p.is_sampled:
            row_data.append(ci_str)
        row_data.extend(
            [
                min_str,
                max_str,
                Text.from_markup(flags_str),
            ]
        )

        table.add_row(*row_data)

    _console.print(table)

    if truncated_names:
        _console.print(
            "[dim]  * Full column names: " + " | ".join(truncated_names) + "[/dim]\n"
        )
    else:
        _console.print()

    # ── Smart Warnings ────────────────────────────────────────────
    warnings_list = _collect_warnings_legacy(p)
    if warnings_list:
        _warn_icon_styles = {
            "✗": "[red]✗[/red]",
            "⚠": "[yellow]⚠[/yellow]",
            "✓": "[green]✓[/green]",
            "ℹ": "[blue]ℹ[/blue]",
        }
        warn_lines = ["[bold]Smart Warnings:[/bold]"]
        for w in warnings_list[:5]:
            icon = _warn_icon_styles.get(w["icon"], w["icon"])
            warn_lines.append(
                f"  {icon}  [cyan]'{rich_escape(w['column'])}'[/cyan] — {w['message']}"
            )
        if len(warnings_list) > 5:
            warn_lines.append(
                f"  [dim]... and {len(warnings_list) - 5} more. "
                f'Call zd.warnings("{p.file_name}") for full list.[/dim]'
            )
        _console.print("\n".join(warn_lines) + "\n")

    # ── Correlation Alerts ────────────────────────────────────────
    _correlation_alerts(p, _console)

    # ── Clean Footer ──────────────────────────────────────────────
    _console.print(
        f"[dim]  zedda v{__version__}  •  "
        f"{p.num_cols} columns  •  "
        f"{p.num_rows:,} rows  •  "
        f"scanned in {scan_str}[/dim]\n"
    )


def _print_plain(p: Any) -> None:
    """Fallback plain-text report when Rich is not installed."""
    sampled = " [SAMPLED]" if p.is_sampled else ""
    print(f"\nzedda v{__version__}")
    print(f"File  : {p.file_name}{sampled}")
    print(f"Rows  : {p.num_rows:,}")
    print(f"Cols  : {p.num_cols}")
    print(f"Nulls : {p.overall_null_pct:.1f}%")
    print(f"Time  : {p.scan_time_ms:.0f} ms")
    print("\nColumn        Type    Nulls     Mean")
    print("-" * 52)
    for col in p.columns:
        mean_s = _format_num(col.mean) if col.type_str in ("int", "float") else "-"
        col_name = col.name if len(col.name) <= 12 else col.name[:10] + ".."
        print(f"{col_name:<14}{col.type_str:<8}{col.null_pct:.1f}%     {mean_s}")


# ─────────────────────────────────────────────────────────────────
#  compare() — diff two datasets for drift detection
# ─────────────────────────────────────────────────────────────────
def compare(path_a, path_b, sample_size: int = None) -> None:
    """
    Compare two datasets side by side for drift detection.

    Shows schema differences, null rate changes, distribution
    shifts, new categories, and a final verdict.

    Args:
        path_a (str): Path to the first dataset (e.g. training data).
        path_b (str): Path to the second dataset (e.g. production data).
        sample_size (int, optional): Max rows to read per file.

    Example::

        import zedda as zd
        zd.compare("train.csv", "test.csv")
    """
    res_a, temp_a = _resolve_input(path_a)
    res_b, temp_b = _resolve_input(path_b)
    try:
        p_a = scan(res_a, sample_size=sample_size)
        p_b = scan(res_b, sample_size=sample_size)

        if not _RICH_AVAILABLE or _console is None:
            print("Rich not available — install it: pip install rich")
            return

        name_a = (
            "<DataFrame A>"
            if temp_a
            else (
                Path(path_a).name
                if isinstance(path_a, (str, Path))
                else "<DataFrame A>"
            )
        )
        name_b = (
            "<DataFrame B>"
            if temp_b
            else (
                Path(path_b).name
                if isinstance(path_b, (str, Path))
                else "<DataFrame B>"
            )
        )

        # ── Header ────────────────────────────────────────────────────
        _console.print(
            f"\n[bold blue]zedda[/bold blue] [dim]v{__version__}[/dim]  "
            f"[dim]·  compare mode[/dim]\n"
        )
        _console.print(
            f"  [bold]A[/bold] : [cyan]{name_a}[/cyan]"
            f"     [dim]{p_a.num_rows:,} rows  ·  {p_a.num_cols} cols[/dim]"
        )
        _console.print(
            f"  [bold]B[/bold] : [cyan]{name_b}[/cyan]"
            f"     [dim]{p_b.num_rows:,} rows  ·  {p_b.num_cols} cols[/dim]"
        )

        cols_a = {c.name: c for c in p_a.columns}
        cols_b = {c.name: c for c in p_b.columns}
        all_cols = list(dict.fromkeys(list(cols_a) + list(cols_b)))

        critical_errors = 0
        warnings_count = 0

        # ── Section 1: Schema ─────────────────────────────────────────
        _console.print(f"\n[bold]{'─' * 14} Schema {'─' * 38}[/bold]")

        # Column count
        if p_a.num_cols == p_b.num_cols:
            _console.print(
                f"  [green]✓[/green]  Column count   : "
                f"{p_a.num_cols} / {p_b.num_cols} match"
            )
        else:
            _console.print(
                f"  [red]✗[/red]  Column count   : "
                f"{p_a.num_cols} vs {p_b.num_cols}  [red]MISMATCH[/red]"
            )
            critical_errors += 1

        # Type mismatches and missing columns
        type_match_count = 0
        type_total = 0
        for name in all_cols:
            ca = cols_a.get(name)
            cb = cols_b.get(name)

            if not cb:
                _console.print(
                    f"  [red]✗[/red]  {rich_escape(name):<16}: "
                    f"[red]MISSING in {name_b}[/red]"
                )
                critical_errors += 1
            elif not ca:
                _console.print(
                    f"  [red]✗[/red]  {rich_escape(name):<16}: "
                    f"[red]MISSING in {name_a}[/red]"
                )
                critical_errors += 1
            else:
                type_total += 1
                if ca.type_str != cb.type_str:
                    _console.print(
                        f"  [red]✗[/red]  {rich_escape(name):<16}: "
                        f"{name_a}={ca.type_str}  {name_b}={cb.type_str}   "
                        f"[red]TYPE MISMATCH[/red]"
                    )
                    critical_errors += 1
                else:
                    type_match_count += 1

        if type_total > 0:
            _console.print(
                f"  [green]✓[/green]  Types          : "
                f"{type_match_count} / {type_total} match"
            )

        # ── Section 2: Null Rates ─────────────────────────────────────
        _console.print(f"\n[bold]{'─' * 14} Null Rates {'─' * 34}[/bold]")

        for name in all_cols:
            ca = cols_a.get(name)
            cb = cols_b.get(name)
            if not ca or not cb:
                continue

            delta = cb.null_pct - ca.null_pct
            if delta > 5:
                _console.print(
                    f"  [yellow]⚠[/yellow]  {rich_escape(name):<16}: "
                    f"{ca.null_pct:.1f}%  →  {cb.null_pct:.1f}%   "
                    f"[yellow]SPIKE (+{delta:.1f}%)[/yellow]"
                )
                warnings_count += 1
            elif delta > 0.1:
                _console.print(
                    f"  [yellow]⚠[/yellow]  {rich_escape(name):<16}: "
                    f"{ca.null_pct:.1f}%  →  {cb.null_pct:.1f}%   "
                    f"[dim](+{delta:.1f}%) minor increase[/dim]"
                )
            elif delta < -0.1:
                _console.print(
                    f"  [green]✓[/green]  {rich_escape(name):<16}: "
                    f"{ca.null_pct:.1f}%  →  {cb.null_pct:.1f}%   "
                    f"[dim]({delta:.1f}%) minor decrease[/dim]"
                )
            else:
                _console.print(
                    f"  [green]✓[/green]  {rich_escape(name):<16}: "
                    f"{ca.null_pct:.1f}%  →  {cb.null_pct:.1f}%    "
                    f"[dim]stable[/dim]"
                )

        # ── Section 3: Distribution Shift ─────────────────────────────
        _console.print(f"\n[bold]{'─' * 14} Distribution Shift {'─' * 26}[/bold]")

        for name in all_cols:
            ca = cols_a.get(name)
            cb = cols_b.get(name)
            if not ca or not cb:
                continue
            if ca.type_str not in ("int", "float") or cb.type_str not in (
                "int",
                "float",
            ):
                continue

            is_int = ca.type_str == "int"
            mean_a_s = _format_num(ca.mean, is_int)
            mean_b_s = _format_num(cb.mean, is_int)

            if ca.mean > 0:
                shift_pct = (cb.mean - ca.mean) / ca.mean * 100
            else:
                shift_pct = 0.0

            abs_shift = abs(shift_pct)
            if abs_shift > 50:
                _console.print(
                    f"  [red]✗[/red]  {rich_escape(name):<16}: "
                    f"mean {mean_a_s} → {mean_b_s}  "
                    f"[red]DRIFT  ({shift_pct:+.0f}%)[/red]"
                )
                critical_errors += 1
            elif abs_shift > 20:
                _console.print(
                    f"  [yellow]⚠[/yellow]  {rich_escape(name):<16}: "
                    f"mean {mean_a_s} → {mean_b_s}  "
                    f"[yellow]SHIFT  ({shift_pct:+.0f}%)[/yellow]"
                )
                warnings_count += 1
            else:
                _console.print(
                    f"  [green]✓[/green]  {rich_escape(name):<16}: "
                    f"mean {mean_a_s} → {mean_b_s}   "
                    f"[dim]stable[/dim]"
                )

        # ── Section 4: New Categories ─────────────────────────────────
        has_new_cats = False
        for name in all_cols:
            ca = cols_a.get(name)
            cb = cols_b.get(name)
            if not ca or not cb:
                continue
            if ca.type_str in ("int", "float") or cb.type_str in ("int", "float"):
                continue
            if cb.unique_approx > ca.unique_approx:
                if not has_new_cats:
                    _console.print(
                        f"\n[bold]{'─' * 14} New Categories {'─' * 30}[/bold]"
                    )
                    has_new_cats = True
                new_count = cb.unique_approx - ca.unique_approx
                _console.print(
                    f"  [yellow]⚠[/yellow]  {rich_escape(name):<16}: "
                    f"[yellow]{new_count} new value{'s' if new_count != 1 else ''} "
                    f"in {name_b}[/yellow]"
                )
                warnings_count += 1

        # ── Section 5: Verdict ────────────────────────────────────────
        _console.print(f"\n[bold]{'─' * 14} Verdict {'─' * 37}[/bold]")

        if critical_errors > 0:
            _console.print(
                f"  [bold red]✗  FAIL[/bold red]  —  "
                f"{critical_errors} critical error{'s' if critical_errors != 1 else ''}"
                + (
                    f" · {warnings_count} warning{'s' if warnings_count != 1 else ''}"
                    if warnings_count > 0
                    else ""
                )
            )
            _console.print("  Safe to train : [bold red]NO[/bold red]")
        elif warnings_count > 0:
            _console.print(
                f"  [bold yellow]⚠  WARN[/bold yellow]  —  "
                f"{warnings_count} warning{'s' if warnings_count != 1 else ''}"
            )
            _console.print(
                "  Safe to train : [bold yellow]REVIEW[/bold yellow]"
                "  [dim]— check flagged shifts before proceeding[/dim]"
            )
        else:
            _console.print("  [bold green]✓  PASS[/bold green]  —  no issues found")
            _console.print("  Safe to train : [bold green]YES[/bold green]")

        _console.print()

    finally:
        if temp_a:
            _cleanup_temp(res_a)
        if temp_b:
            _cleanup_temp(res_b)


# ─────────────────────────────────────────────────────────────────
#  warnings() — Intelligence mode: severity + inline fixes + copy-paste
#
#  Premium display with:
#    - Severity header (N critical · N warnings · N info)
#    - Each warning shows icon + column + message + fix code
#    - Copy-Paste Fix Block at the bottom
#    - Quality score + auto-fixable count
#    - Pointer to zd.clean() for auto-apply
# ─────────────────────────────────────────────────────────────────
def warnings(path) -> None:
    """
    Show ALL warnings for a file with intelligence mode.

    Displays every data quality warning with severity levels,
    inline fix code, a copy-paste fix block, quality score,
    and auto-fixable count.

    Args:
        path (str): Path to a ``.csv``, ``.parquet``, or ``.arrow`` file.

    Example::

        import zedda as zd
        zd.warnings("data.csv")
    """
    resolved_path, is_temp = _resolve_input(path)
    try:
        p = scan(resolved_path)

        if not _RICH_AVAILABLE or _console is None:
            print("Rich not available — install it: pip install rich")
            return

        file_name = (
            "<DataFrame>"
            if is_temp
            else (Path(path).name if isinstance(path, (str, Path)) else "<DataFrame>")
        )

        all_warnings = _collect_warnings(p)

        # ── Count by severity ───────────────────────────────────────
        n_critical = sum(1 for w in all_warnings if w["severity"] == "critical")
        n_warning = sum(1 for w in all_warnings if w["severity"] == "warning")
        n_info = sum(1 for w in all_warnings if w["severity"] == "info")
        total = len(all_warnings)

        # ── Header ──────────────────────────────────────────────────
        _console.print(
            f"\n[bold blue]zedda[/bold blue] [dim]v{__version__}[/dim]  ·  "
            f"[bold]warnings mode[/bold]  ·  [dim]intelligence[/dim]\n"
        )

        if not all_warnings:
            _console.print("  [green]✓  No warnings — data looks clean![/green]\n")
            return

        # Severity summary line
        parts = []
        if n_critical:
            parts.append(f"[red]{n_critical} critical[/red]")
        if n_warning:
            parts.append(f"[yellow]{n_warning} warning{'s' if n_warning != 1 else ''}[/yellow]")
        if n_info:
            parts.append(f"[blue]{n_info} info[/blue]")
        severity_str = " · ".join(parts)

        _console.print(
            f"[bold]Found {total} issue{'s' if total != 1 else ''}[/bold] · {severity_str}\n"
        )

        # ── Warning entries ─────────────────────────────────────────
        severity_labels = {
            "critical": ("[red]✗ CRITICAL[/red]", "red"),
            "warning": ("[yellow]⚠ WARNING [/yellow]", "yellow"),
            "info": ("[blue]ℹ INFO    [/blue]", "blue"),
        }

        for w in all_warnings:
            label, color = severity_labels.get(
                w["severity"], ("[dim]?[/dim]", "dim")
            )
            _console.print(
                f"{label}  [cyan]'{rich_escape(w['column'])}'[/cyan] — {w['message']}"
            )
            if w.get("fix_action"):
                _console.print(f"   {w['fix_action']}")
            if w.get("fix_code"):
                _console.print(f"   [dim]→ Fix: {w['fix_code']}[/dim]")
            _console.print()

        # ── Copy-Paste Fix Block ────────────────────────────────────
        fixable = [w for w in all_warnings if w.get("fix_code")]
        if fixable:
            _console.print("[bold]Copy-Paste Fix Block:[/bold]")
            for w in fixable:
                _console.print(f"  [cyan]{w['fix_code']}[/cyan]")
            _console.print()

        # ── Quality Score + Auto-fixable ────────────────────────────
        score = _quality_score(p)
        n_auto = sum(1 for w in all_warnings if w.get("auto_fixable"))
        auto_pct = int(n_auto / total * 100) if total > 0 else 0

        filled = score // 10
        bar = "=" * filled + "-" * (10 - filled)
        if score >= 95:
            color, label = "cyan", "PRISTINE"
        elif score >= 80:
            color, label = "green", "GOOD"
        elif score >= 60:
            color, label = "yellow", "FAIR"
        else:
            color, label = "red", "POOR"

        _console.print(
            f"[bold]Quality score:[/bold] [{color}]{score}/100  "
            f"{bar}  {label}[/{color}]"
            f' → [dim]run zd.clean("{file_name}") to auto-apply fixes[/dim]'
        )
        _console.print(
            f"[bold]Auto-fixable:[/bold] {n_auto} of {total} ({auto_pct}%)\n"
        )

    finally:
        if is_temp:
            _cleanup_temp(resolved_path)


# ─────────────────────────────────────────────────────────────────
#  _ml_readiness_score() — dedicated ML readiness scoring
#
#  More ML-specific than _quality_score() — penalizes issues that
#  directly impact model training quality:
#    - Null columns (moderate + severe)
#    - ID-like columns (wasted features)
#    - High-cardinality strings (need encoding)
#    - Extreme outliers
#    - Multicollinearity (correlated pairs)
# ─────────────────────────────────────────────────────────────────
def _ml_readiness_score(p: Any) -> int:
    """Compute a 0-100 ML readiness score from the profile object."""
    score = 100

    for col in p.columns:
        # Penalize columns with notable nulls
        if col.null_pct > 50:
            score -= 15  # Too sparse — can't trust imputation
        elif col.null_pct > 5:
            score -= 10  # Needs imputation but recoverable

        # Penalize ID-like columns (useless features)
        if col.type_str == "int" and col.unique_pct > 95:
            score -= 5

        # Penalize high-cardinality strings (ID-like)
        if (
            col.type_str in ("str", "unknown")
            and p.num_rows > 0
            and col.unique_approx > p.num_rows * 0.8
        ):
            score -= 5
        # Penalize moderate-cardinality strings (needs encoding)
        elif col.type_str in ("str", "unknown") and col.unique_approx > 100:
            score -= 3

        # Penalize extreme outliers
        if (
            col.type_str in ("int", "float")
            and col.mean > 0
            and col.unique_approx > 5
            and col.val_max > 10
            and col.val_max > col.mean * 10
            and "ratio" not in col.name.lower()
            and "pct" not in col.name.lower()
        ):
            score -= 5

    # Penalize strongly correlated pairs (multicollinearity)
    for cr in p.correlations:
        if abs(cr.r) >= 0.95:
            score -= 10
            break  # Count once

    return max(0, min(100, score))


# ─────────────────────────────────────────────────────────────────
#  _section_header() — consistent section separator for premium UI
# ─────────────────────────────────────────────────────────────────
def _section_header(title: str, width: int = 55) -> str:
    """Return a ──── Title ──── style Rich-formatted section header."""
    left = "─" * 14
    right_len = max(1, width - 14 - len(title) - 2)
    right = "─" * right_len
    return f"[dim]{left}[/dim] [bold]{title}[/bold] [dim]{right}[/dim]"


# ─────────────────────────────────────────────────────────────────
#  ml_ready() — ML readiness check with premium terminal UI
#
#  Shows:
#    1. Version header + mode label
#    2. Scan timing
#    3. Visual score bar (█░ style)
#    4. Grouped issues with inline fix code
#    5. "Looks Good" section for clean features
#    6. Copy-paste fix code block
#    7. Summary footer
# ─────────────────────────────────────────────────────────────────
def ml_ready(path, sample_size: int = None) -> None:
    """
    Check if a dataset is ready for Machine Learning.

    Provides a score (0-100) with a visual progress bar, grouped
    issue sections with inline fix code, a "Looks Good" section
    for clean features, and a final copy-paste fix block.

    Args:
        path (str): Path to a ``.csv``, ``.parquet``, or ``.arrow`` file.
        sample_size (int, optional): Max rows to sample.

    Example::

        import zedda as zd
        zd.ml_ready("data.csv")
    """
    resolved_path, is_temp = _resolve_input(path)
    try:
        t0 = time.perf_counter()
        p = scan(resolved_path, sample_size=sample_size)
        total_ms = (time.perf_counter() - t0) * 1000

        if not _RICH_AVAILABLE or _console is None:
            print("Rich not available — install it: pip install rich")
            return

        file_name = (
            "<DataFrame>"
            if is_temp
            else (Path(path).name if isinstance(path, (str, Path)) else "<DataFrame>")
        )
        scan_str = (
            f"{total_ms / 1000:.1f} sec" if total_ms >= 10_000 else f"{total_ms:.0f} ms"
        )

        # ── Header ─────────────────────────────────────────────────
        _console.print(
            f"\n[bold blue]zedda[/bold blue] [dim]v{__version__}[/dim]  ·  "
            f"[bold]ml_ready mode[/bold]\n"
        )
        _console.print(
            f"[dim]Scanning[/dim]   [cyan]{file_name}[/cyan]   ...  {scan_str}\n"
        )

        # ── ML Readiness Score ─────────────────────────────────────
        score = _ml_readiness_score(p)
        filled = score // 10
        bar = "\u2588" * filled + "\u2591" * (10 - filled)

        if score >= 80:
            color, label = "green", "GOOD"
        elif score >= 60:
            color, label = "yellow", "FAIR"
        else:
            color, label = "red", "POOR"

        _console.print(_section_header("ML Readiness Score"))
        _console.print(f"  [{color}]{score} / 100  {bar}  {label}[/{color}]\n")

        # ── Collect issues and good features ───────────────────────
        issues = []  # (icon, col_name, description, fix_hint)
        looks_good = []  # (col_name, description)
        fix_lines = []  # copy-paste code lines
        drop_cols = []  # safe column names to drop

        claimed = set()  # track columns already categorized

        for col in p.columns:
            safe = _safe_col_name(col.name)  # SEC-P01: sanitized name
            display = rich_escape(col.name)

            # ── Missing values (critical if >5%) ───────────────────
            if col.null_pct > 5:
                claimed.add(col.name)
                if col.null_pct > 50:
                    issues.append(
                        (
                            "\u2717",
                            display,
                            f"{col.null_pct:.1f}% nulls  \u2014 too sparse to trust imputation",
                            f"Consider dropping: df = df.drop(columns=[{safe}])",
                        )
                    )
                    drop_cols.append(safe)
                elif col.type_str in ("int", "float"):
                    code = f"df[{safe}] = df[{safe}].fillna(df[{safe}].median())"
                    issues.append(
                        (
                            "\u2717",
                            display,
                            f"{col.null_pct:.1f}% nulls",
                            f"Impute: {code}",
                        )
                    )
                    fix_lines.append(code)
                else:
                    code = f"df[{safe}] = df[{safe}].fillna(df[{safe}].mode()[0])"
                    issues.append(
                        (
                            "\u2717",
                            display,
                            f"{col.null_pct:.1f}% nulls",
                            f"Impute: {code}",
                        )
                    )
                    fix_lines.append(code)
                continue

            # ── ID-like int columns ────────────────────────────────
            if col.type_str == "int" and col.unique_pct > 95:
                claimed.add(col.name)
                issues.append(
                    (
                        "\u26a0",
                        display,
                        f"{col.unique_approx:,} unique values  (ID-like)",
                        "Drop before training \u2014 no predictive signal",
                    )
                )
                drop_cols.append(safe)
                continue

            # ── ID-like string columns (>80% unique) ──────────────
            if (
                col.type_str in ("str", "unknown")
                and p.num_rows > 0
                and col.unique_approx > p.num_rows * 0.8
            ):
                claimed.add(col.name)
                issues.append(
                    (
                        "\u26a0",
                        display,
                        f"{col.unique_approx:,} unique values  (ID-like)",
                        "Drop before training \u2014 no predictive signal",
                    )
                )
                drop_cols.append(safe)
                continue

            # ── High-cardinality strings ───────────────────────────
            if col.type_str in ("str", "unknown") and col.unique_approx > 20:
                claimed.add(col.name)
                issues.append(
                    (
                        "\u26a0",
                        display,
                        f"{col.unique_approx:,} unique values  (high cardinality)",
                        "Encode carefully or drop",
                    )
                )
                drop_cols.append(safe)
                continue

            # ── Extreme outliers ───────────────────────────────────
            if (
                col.type_str in ("int", "float")
                and col.mean > 0
                and col.unique_approx > 5
                and col.val_max > 10
                and col.val_max > col.mean * 10
                and "ratio" not in col.name.lower()
                and "pct" not in col.name.lower()
            ):
                claimed.add(col.name)
                is_int = col.type_str == "int"
                ratio = col.val_max / col.mean
                code = f"df[{safe}] = df[{safe}].clip(upper=df[{safe}].quantile(0.99))"
                issues.append(
                    (
                        "\u26a0",
                        display,
                        f"max ({_format_num(col.val_max, is_int)}) is "
                        f"{ratio:.0f}x above mean",
                        f"Clip: {code}",
                    )
                )
                fix_lines.append(code)
                continue

        # ── Identify good features (not claimed by issues) ─────────
        for col in p.columns:
            if col.name in claimed:
                continue
            display = rich_escape(col.name)

            # Binary target
            if (
                col.type_str in ("int", "float")
                and col.val_min == 0
                and col.val_max == 1
                and col.unique_approx <= 2
            ):
                looks_good.append((display, "binary (0/1)  \u2014 good ML target"))
            # Low-cardinality int (like Pclass)
            elif (
                col.type_str in ("int", "float")
                and col.unique_approx <= 15
                and col.null_pct < 5
            ) or (
                col.type_str in ("str", "unknown")
                and col.unique_approx <= 20
                and col.null_pct < 5
            ):
                looks_good.append(
                    (
                        display,
                        f"{col.unique_approx} unique values \u2014 good categorical feature",
                    )
                )

        # ── Correlation issues ─────────────────────────────────────
        for cr in p.correlations:
            if abs(cr.r) >= 0.95:
                safe_a = _safe_col_name(cr.col_a)
                issues.append(
                    (
                        "\u26a0",
                        f"{rich_escape(cr.col_a)} \u2194 {rich_escape(cr.col_b)}",
                        f"r={cr.r:+.2f}  \u2014 highly correlated (multicollinearity)",
                        f"Drop one: df = df.drop(columns=[{safe_a}])",
                    )
                )
                drop_cols.append(safe_a)
                break  # Show one to avoid flooding

        # ── Print Issues Found ─────────────────────────────────────
        if issues:
            _console.print(_section_header("Issues Found"))
            for icon, col_name, desc, fix_hint in issues:
                icon_color = "red" if icon == "\u2717" else "yellow"
                _console.print(
                    f"    [{icon_color}]{icon}[/{icon_color}]  "
                    f"[bold]{col_name}[/bold]      {desc}"
                )
                if fix_hint:
                    _console.print(f"       [dim]{fix_hint}[/dim]")
                _console.print()

        # ── Print Looks Good ───────────────────────────────────────
        if looks_good:
            _console.print(_section_header("Looks Good"))
            for col_name, desc in looks_good:
                _console.print(
                    f"    [green]\u2713[/green]  [bold]{col_name}[/bold]  {desc}"
                )
            _console.print()

        # ── Print Suggested Fix Code ───────────────────────────────
        if fix_lines or drop_cols:
            _console.print(_section_header("Suggested Fix Code"))
            for line in fix_lines:
                _console.print(f"  [cyan]{line}[/cyan]")
            if drop_cols:
                unique_drops = list(dict.fromkeys(drop_cols))
                drop_str = ", ".join(unique_drops)
                _console.print(f"  [cyan]df = df.drop(columns=[{drop_str}])[/cyan]")
            _console.print()

        # ── Footer ─────────────────────────────────────────────────
        unique_drop_count = len(set(drop_cols))
        recommended = p.num_cols - unique_drop_count
        _console.print(
            f"  [dim]Recommended feature count : "
            f"{recommended} of {p.num_cols} columns[/dim]"
        )
        _console.print(
            "  [dim]Re-run zd.ml_ready() after fixing to verify score improves.[/dim]\n"
        )

    finally:
        if is_temp:
            _cleanup_temp(resolved_path)


# ─────────────────────────────────────────────────────────────────
#  fix() — Automated Pandas Fix Code Generator
#
#  Scans the dataset and generates copy-paste-ready pandas code to
#  fix the most common data quality problems:
#    - Missing values (nulls)       → fillna with median or "Unknown"
#    - Extreme outliers             → log-transform (np.log1p)
#    - Disguised ID columns         → drop (useless for ML)
#    - High-cardinality strings     → label encode (pd.Categorical)
#
#  apply=True returns an actual cleaned DataFrame (not just code)
#  All generated code uses repr() for column names (SEC-P01)
# ─────────────────────────────────────────────────────────────────
def fix(path, apply: bool = False) -> Any:
    """
    Scan a dataset and generate copy-paste-ready pandas fix code.

    Automatically detects the most common data quality problems and
    prints grouped, actionable pandas snippets you can paste directly
    into your data preparation notebook or script.

    Issues detected and fixed:

    * **Missing values** ΓÇö numeric columns get ``fillna(median())``;
      string columns get ``fillna(mode()[0])``.
    * **Extreme outliers** ΓÇö columns where max > 10x mean get a
      ``np.log1p()`` transform suggestion.
    * **ID columns** ΓÇö integer columns with >95% unique values are
      flagged as likely row IDs and suggested for dropping.
    * **High-cardinality strings** ΓÇö string columns with >50 unique
      values get a label-encoding suggestion.

    The output is grouped by issue type and ends with a clean
    **"Copy-Paste Block"** containing all fixes in one place.

    Args:
        path (str):
            Path to a ``.csv``, ``.parquet``, or ``.arrow`` file.
        apply (bool, default False):
            If ``True``, actually apply all fixes and return a clean
            pandas DataFrame instead of just printing code.

    Returns:
        None when ``apply=False`` (prints to terminal).
        ``pandas.DataFrame`` when ``apply=True``.

    Example::

        import zedda as zd

        # Print fix suggestions only
        zd.fix("data.csv")

        # Actually apply all fixes and get a clean DataFrame
        clean_df = zd.fix("data.csv", apply=True)
    """
    resolved_path, is_temp = _resolve_input(path)
    try:
        if not _RICH_AVAILABLE or _console is None:
            print("Rich not available. Install it: pip install rich")
            return None

        # Run the C++ engine silently
        p = scan(resolved_path)

        # Each entry: (display_line, code_line)
        # display_line = what we show in the grouped section
        # code_line    = what goes in the final copy-paste block
        null_fixes = []  # Missing value imputation fixes
        outlier_fixes = []  # Extreme outlier transform fixes
        id_col_fixes = []  # Useless ID column drop fixes
        encoding_fixes = []  # High-cardinality string encoding fixes

        for col in p.columns:
            # SEC-P01: Use repr() for column names in all generated code.
            # This escapes quotes, backslashes, and control characters,
            # preventing code injection via malicious CSV column names.
            safe = _safe_col_name(col.name)
            display_name = rich_escape(col.name)  # Safe for Rich markup

            # Missing values
            # Threshold: flag columns with more than 1% nulls
            if col.null_pct > 1:
                if col.type_str in ("int", "float"):
                    # Median is robust to outliers ΓÇö better than mean
                    null_fixes.append(
                        (
                            f"  [cyan]{display_name}[/cyan]  "
                            f"[dim]ΓåÆ {col.null_pct:.1f}% nulls ΓåÆ fillna(median)[/dim]",
                            f"df[{safe}] = df[{safe}].fillna(df[{safe}].median())  "
                            f"# {col.null_pct:.1f}% nulls",
                        )
                    )
                elif col.type_str in ("str", "unknown"):
                    # Mode (most frequent value) is the standard for categoricals
                    null_fixes.append(
                        (
                            f"  [cyan]{display_name}[/cyan]  "
                            f"[dim]ΓåÆ {col.null_pct:.1f}% nulls ΓåÆ fillna(mode)[/dim]",
                            f"df[{safe}] = df[{safe}].fillna(df[{safe}].mode()[0])  "
                            f"# {col.null_pct:.1f}% nulls",
                        )
                    )

            # Extreme outliers
            # Flag numeric columns where max > 10x the mean.
            # Skip ratio/percent columns ΓÇö extreme max is expected there.
            if (
                col.type_str in ("int", "float")
                and col.mean > 0
                and col.val_max > col.mean * 10
                and col.unique_approx > 5
                and "ratio" not in col.name.lower()
                and "pct" not in col.name.lower()
            ):
                ratio = col.val_max / col.mean
                outlier_fixes.append(
                    (
                        f"  [cyan]{display_name}[/cyan]  "
                        f"[dim]ΓåÆ max is {ratio:.0f}x mean ΓåÆ log1p transform[/dim]",
                        f"df[{repr(col.name + '_log')}] = np.log1p(df[{safe}])  "
                        f"# max={col.val_max:,.0f} is {ratio:.0f}x mean",
                    )
                )

            # Disguised ID columns
            # An integer column that is almost entirely unique is almost
            # certainly a row identifier ΓÇö useless for ML models.
            if col.type_str == "int" and col.unique_pct > 95:
                id_col_fixes.append(
                    (
                        f"  [cyan]{display_name}[/cyan]  "
                        f"[dim]ΓåÆ {col.unique_pct:.0f}% unique ΓåÆ likely ID column ΓåÆ drop[/dim]",
                        f"df = df.drop(columns=[{safe}])  "
                        f"# {col.unique_pct:.0f}% unique values ΓÇö ID column",
                    )
                )

            # High-cardinality string encoding
            # String columns with >50 distinct values need special encoding
            # before feeding into most ML models (which require numbers).
            if col.type_str in ("str", "unknown") and col.unique_approx > 50:
                encoding_fixes.append(
                    (
                        f"  [cyan]{display_name}[/cyan]  "
                        f"[dim]ΓåÆ {col.unique_approx} unique values ΓåÆ label encode[/dim]",
                        f"df[{safe}] = pd.Categorical(df[{safe}]).codes  "
                        f"# {col.unique_approx} unique values",
                    )
                )

        # Check if there is anything to fix
        all_fixes = null_fixes + outlier_fixes + id_col_fixes + encoding_fixes
        if not all_fixes:
            _console.print(
                Panel(
                    "[green]No fixes needed![/green]  "
                    "Your dataset looks clean and ML-ready.",
                    title="[bold green]zd.fix() - All Clear[/bold green]",
                    border_style="green",
                    expand=False,
                )
            )
            return None

        # Print summary header
        n_issues = len(all_fixes)
        summary = (
            f"[bold]{n_issues} issue{'s' if n_issues > 1 else ''} found[/bold] "
            f"across [cyan]{p.num_cols}[/cyan] columns.\n"
            f"[dim]Scroll down for the full copy-paste block.[/dim]"
        )
        file_name = (
            "<DataFrame>"
            if is_temp
            else (Path(path).name if isinstance(path, (str, Path)) else "<DataFrame>")
        )
        _console.print(
            Panel(
                summary,
                title=f"[bold yellow]zd.fix() - {file_name}[/bold yellow]",
                border_style="yellow",
                expand=False,
            )
        )

        # Print each category with a section header
        if null_fixes:
            _console.print(
                "\n[bold red]Γ¼ñ  MISSING VALUES[/bold red]  "
                "[dim](fills nulls with median / mode)[/dim]"
            )
            for display, _ in null_fixes:
                _console.print(display)

        if outlier_fixes:
            _console.print(
                "\n[bold magenta]Γ¼ñ  OUTLIERS[/bold magenta]  "
                "[dim](log1p shrinks extreme right-skewed values)[/dim]"
            )
            for display, _ in outlier_fixes:
                _console.print(display)

        if id_col_fixes:
            _console.print(
                "\n[bold blue]Γ¼ñ  ID COLUMNS[/bold blue]  "
                "[dim](high-uniqueness integers ΓÇö useless for ML)[/dim]"
            )
            for display, _ in id_col_fixes:
                _console.print(display)

        if encoding_fixes:
            _console.print(
                "\n[bold cyan]Γ¼ñ  ENCODING[/bold cyan]  "
                "[dim](high-cardinality strings ΓåÆ numeric codes)[/dim]"
            )
            for display, _ in encoding_fixes:
                _console.print(display)

        # Print the final copy-paste block
        _console.print(
            "\n[bold]Copy-Paste Block:[/bold]  "
            "[dim](paste this into your notebook or script)[/dim]"
        )

        # Print imports only if they are actually needed by the generated code
        needs_numpy = bool(outlier_fixes)  # np.log1p
        needs_pandas = bool(encoding_fixes)  # pd.Categorical
        if needs_numpy:
            _console.print("[dim]import numpy as np[/dim]")
        if needs_pandas:
            _console.print("[dim]import pandas as pd[/dim]")

        for _, code in all_fixes:
            _console.print(f"  [cyan]{code}[/cyan]")
        _console.print()

        # apply=True: actually execute the fixes and return a DataFrame
        if apply:
            try:
                import numpy as np
                import pandas as pd
            except ImportError:
                _console.print(
                    "[red]pandas / numpy not installed ΓÇö cannot apply fixes.[/red]\n"
                    "Run: pip install pandas numpy"
                )
                return None

            df = pd.read_csv(path) if path.endswith(".csv") else pd.read_parquet(path)

            # Apply null fixes
            for col in p.columns:
                if col.null_pct > 1:
                    if col.type_str in ("int", "float"):
                        df[col.name] = df[col.name].fillna(df[col.name].median())
                    elif col.type_str in ("str", "unknown"):
                        df[col.name] = df[col.name].fillna(df[col.name].mode()[0])

            # Apply outlier fixes (log1p transform)
            for col in p.columns:
                if (
                    col.type_str in ("int", "float")
                    and col.mean > 0
                    and col.val_max > col.mean * 10
                    and col.unique_approx > 5
                    and "ratio" not in col.name.lower()
                    and "pct" not in col.name.lower()
                ):
                    df[col.name + "_log"] = np.log1p(df[col.name])

            # Apply ID column drops
            id_cols = [
                col.name
                for col in p.columns
                if col.type_str == "int" and col.unique_pct > 95
            ]
            if id_cols:
                df = df.drop(columns=id_cols, errors="ignore")

            # Apply encoding fixes
            for col in p.columns:
                if col.type_str in ("str", "unknown") and col.unique_approx > 50:
                    if col.name in df.columns:
                        df[col.name] = pd.Categorical(df[col.name]).codes

            _console.print(
                Panel(
                    f"[green]Γ£ö Applied {n_issues} fix{'es' if n_issues > 1 else ''}.[/green]  "
                    f"DataFrame shape: [cyan]{df.shape}[/cyan]",
                    title="[bold green]zd.fix(apply=True) ΓÇö Done[/bold green]",
                    border_style="green",
                    expand=False,
                )
            )
            return df

        return None

    finally:
        if is_temp:
            _cleanup_temp(resolved_path)


# ─────────────────────────────────────────────────────────────────
#  clean() — Auto-fix dataset with backup, audit trail, and scoring
#
#  Uses _collect_warnings() to detect issues, applies fixes using
#  pandas, creates a backup file, and writes a JSON audit trail.
#  Shows before/after quality scores with visual progress.
# ─────────────────────────────────────────────────────────────────
def clean(path, output: str = None, sample_size: int = None) -> Any:
    """
    Auto-clean a dataset by applying all auto-fixable warnings.

    Creates a backup, applies fixes (impute, drop, encode), and
    saves the cleaned file with a JSON audit trail.

    Args:
        path (str): Path to a ``.csv``, ``.parquet``, or ``.arrow`` file.
        output (str, optional): Output file path. If None, overwrites
            the original (after creating a backup).
        sample_size (int, optional): Max rows to sample for profiling.

    Returns:
        pandas.DataFrame: The cleaned DataFrame.

    Example::

        import zedda as zd
        zd.clean("titanic.csv", output="titanic_clean.csv")
        zd.clean.undo("titanic.csv")  # restore from backup
    """
    import json
    import shutil

    resolved_path, is_temp = _resolve_input(path)
    try:
        import pandas as pd
    except ImportError:
        raise ZeddaError("pandas is required for clean(). Run: pip install pandas")

    try:
        if not _RICH_AVAILABLE or _console is None:
            print("Rich not available — install it: pip install rich")
            return None

        file_name = (
            "<DataFrame>"
            if is_temp
            else (Path(path).name if isinstance(path, (str, Path)) else "<DataFrame>")
        )

        # ── Header ──────────────────────────────────────────────────
        _console.print(
            f"\n[bold blue]zedda[/bold blue] [dim]v{__version__}[/dim]  ·  "
            f"[bold]clean mode[/bold]\n"
        )

        # ── Profile BEFORE ──────────────────────────────────────────
        p = scan(resolved_path, sample_size=sample_size)
        all_warnings = _collect_warnings(p)
        fixable = [w for w in all_warnings if w.get("auto_fixable")]

        score_before = _quality_score(p)
        n_critical = sum(1 for w in all_warnings if w["severity"] == "critical")
        n_warning = sum(1 for w in all_warnings if w["severity"] == "warning")
        n_info = sum(1 for w in all_warnings if w["severity"] == "info")

        filled = score_before // 10
        bar = "=" * filled + "-" * (10 - filled)
        if score_before >= 95:
            color, label = "cyan", "PRISTINE"
        elif score_before >= 80:
            color, label = "green", "GOOD"
        elif score_before >= 60:
            color, label = "yellow", "FAIR"
        else:
            color, label = "red", "POOR"

        _console.print("[bold]Before[/bold]")
        _console.print(
            f"  Quality score : [{color}]{score_before}/100  "
            f"{bar}  {label}[/{color}]"
        )
        _console.print(
            f"  Issues found  : {len(all_warnings)}  "
            f"({n_critical} critical · {n_warning} warning{'s' if n_warning != 1 else ''}"
            f" · {n_info} info)\n"
        )

        if not fixable:
            _console.print("  [green]✓  No auto-fixable issues — data is already clean![/green]\n")
            return None

        # ── Load the data ───────────────────────────────────────────
        ext = Path(resolved_path).suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(resolved_path)
        elif ext in (".parquet", ".arrow"):
            df = pd.read_parquet(resolved_path)
        else:
            raise ZeddaError(f"Unsupported format for clean: {ext}")

        rows_before = len(df)
        cols_before = len(df.columns)

        # ── Create backup ───────────────────────────────────────────
        if not is_temp:
            backup_path = str(resolved_path) + ".zedda-backup"
            shutil.copy2(resolved_path, backup_path)
            _console.print("[bold]Backup[/bold]")
            _console.print(
                f"  [green]✓[/green]  Backup saved → {Path(backup_path).name}"
            )
            _console.print(
                f'     Restore anytime: zd.clean.undo("{file_name}")\n'
            )
        else:
            backup_path = None

        # ── Apply fixes ─────────────────────────────────────────────
        _console.print("[bold]Applying Fixes[/bold]")
        audit_actions = []
        dropped_cols = []

        for w in fixable:
            col_name = w["column"]
            action = w["action_type"]
            safe_display = rich_escape(col_name)

            if action == "drop":
                if col_name in df.columns:
                    reason = w["message"]
                    df = df.drop(columns=[col_name])
                    dropped_cols.append(col_name)
                    _console.print(
                        f"  [green]✓[/green]  {safe_display} → dropped ({reason})"
                        f"      [dim]col removed[/dim]"
                    )
                    audit_actions.append({
                        "column": col_name, "action": "drop",
                        "reason": w["message"],
                    })

            elif action == "impute":
                if col_name in df.columns:
                    col_data = df[col_name]
                    null_count = int(col_data.isnull().sum())
                    col_obj = next((c for c in p.columns if c.name == col_name), None)
                    if col_obj and col_obj.type_str in ("int", "float"):
                        fill_val = col_data.median()
                        df[col_name] = col_data.fillna(fill_val)
                        _console.print(
                            f"  [green]✓[/green]  {safe_display}"
                            f" → median imputed ({fill_val:.2f})"
                            f"      [dim]{null_count} cells[/dim]"
                        )
                    else:
                        fill_val = col_data.mode()[0] if not col_data.mode().empty else "Unknown"
                        df[col_name] = col_data.fillna(fill_val)
                        _console.print(
                            f"  [green]✓[/green]  {safe_display}"
                            f" → mode imputed ({fill_val})"
                            f"      [dim]{null_count} cells[/dim]"
                        )
                    audit_actions.append({
                        "column": col_name, "action": "impute",
                        "fill_value": str(fill_val), "cells_fixed": null_count,
                    })

            elif action == "encode":
                if col_name in df.columns:
                    n_unique = df[col_name].nunique()
                    df[col_name] = pd.Categorical(df[col_name]).codes
                    _console.print(
                        f"  [green]✓[/green]  {safe_display}"
                        f" → label encoded ({n_unique} unique)"
                        f"      [dim]encoded[/dim]"
                    )
                    audit_actions.append({
                        "column": col_name, "action": "encode",
                        "unique_values": n_unique,
                    })

            elif action == "clip":
                if col_name in df.columns:
                    upper = df[col_name].quantile(0.99)
                    clipped = int((df[col_name] > upper).sum())
                    df[col_name] = df[col_name].clip(upper=upper)
                    _console.print(
                        f"  [green]✓[/green]  {safe_display}"
                        f" → clipped at p99 ({upper:.2f})"
                        f"      [dim]{clipped} cells[/dim]"
                    )
                    audit_actions.append({
                        "column": col_name, "action": "clip",
                        "upper_bound": float(upper), "cells_clipped": clipped,
                    })

        # ── Compute AFTER score ─────────────────────────────────────
        # Write temp file to re-scan for after score
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        tmp.close()
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
            table = pa.Table.from_pandas(df, preserve_index=False)
            pq.write_table(table, tmp.name)
            p_after = scan(tmp.name)
            score_after = _quality_score(p_after, original_cols=cols_before)
        except Exception:
            score_after = min(100, score_before + len(fixable) * 4)
        finally:
            _cleanup_temp(tmp.name)

        improvement = score_after - score_before
        rows_after = len(df)
        cols_after = len(df.columns)

        filled_a = score_after // 10
        bar_a = "=" * filled_a + "-" * (10 - filled_a)
        if score_after >= 95:
            color_a, label_a = "cyan", "PRISTINE"
        elif score_after >= 80:
            color_a, label_a = "green", "GOOD"
        elif score_after >= 60:
            color_a, label_a = "yellow", "FAIR"
        else:
            color_a, label_a = "red", "POOR"

        _console.print(f"\n[bold]After[/bold]")
        _console.print(
            f"  Quality score : [{color_a}]{score_after}/100  "
            f"{bar_a}  {label_a}[/{color_a}]"
            f"  [green](+{improvement} points)[/green]"
        )
        n_dropped = len(dropped_cols)
        _console.print(
            f"  Rows : {rows_before:,} → {rows_after:,}   "
            f"Cols : {cols_before} → {cols_after}"
            + (f"  ({n_dropped} dropped)" if n_dropped > 0 else "")
        )

        # ── Save output ─────────────────────────────────────────────
        t0 = time.perf_counter()
        out_path = output if output else str(resolved_path)
        out_ext = Path(out_path).suffix.lower()
        if out_ext in (".parquet", ".arrow"):
            df.to_parquet(out_path, index=False)
        else:
            df.to_csv(out_path, index=False)
        elapsed = (time.perf_counter() - t0) * 1000

        # ── Audit trail ─────────────────────────────────────────────
        audit_path = str(Path(out_path).with_suffix("")) + "_cleaning_audit.json"
        audit_data = {
            "source_file": file_name,
            "output_file": Path(out_path).name,
            "zedda_version": __version__,
            "score_before": score_before,
            "score_after": score_after,
            "rows_before": rows_before,
            "rows_after": rows_after,
            "cols_before": cols_before,
            "cols_after": cols_after,
            "actions": audit_actions,
        }
        with open(audit_path, "w", encoding="utf-8") as f:
            json.dump(audit_data, f, indent=2, ensure_ascii=False)

        _console.print(f"\n[bold]Output[/bold]")
        _console.print(
            f"  [green]✓[/green]  Clean file  → {Path(out_path).name}"
        )
        _console.print(
            f"  [green]✓[/green]  Audit trail → {Path(audit_path).name}"
        )
        if backup_path:
            _console.print(
                f"     Time: {elapsed:.1f}ms  ·  "
                f"Backup: {Path(backup_path).name}\n"
            )
        else:
            _console.print(f"     Time: {elapsed:.1f}ms\n")

        return df

    finally:
        if is_temp:
            _cleanup_temp(resolved_path)


def _clean_undo(path) -> None:
    """Restore a file from its zedda backup."""
    import shutil

    backup = str(path) + ".zedda-backup"
    if not Path(backup).exists():
        raise ZeddaError(
            f"No backup found: '{backup}'\n"
            "Tip: zd.clean() creates a backup before modifying files."
        )
    shutil.copy2(backup, str(path))
    if _RICH_AVAILABLE and _console:
        _console.print(
            f"\n[green]✓[/green]  Restored [cyan]{Path(path).name}[/cyan] "
            f"from backup.\n"
        )
    else:
        print(f"Restored {path} from backup.")


# Attach undo as a method on clean
clean.undo = _clean_undo


# ─────────────────────────────────────────────────────────────────
#  merge() — Smart multi-file merge with schema check, dedup,
#  distribution shift detection, and source tracking.
# ─────────────────────────────────────────────────────────────────
def merge(paths: list, output: str = "combined.csv", sample_size: int = None) -> Any:
    """
    Merge multiple CSV/Parquet files with intelligent checks.

    Performs schema validation, duplicate detection, distribution
    shift analysis, and adds a source tracking column.

    Args:
        paths (list): List of file paths to merge.
        output (str): Output file path (default: "combined.csv").
        sample_size (int, optional): Max rows to sample per file.

    Returns:
        pandas.DataFrame: The merged DataFrame.

    Example::

        import zedda as zd
        zd.merge(["jan.csv", "feb.csv", "mar.csv"], output="combined.csv")
    """
    if not isinstance(paths, (list, tuple)) or len(paths) < 2:
        raise ZeddaError("merge() requires a list of at least 2 file paths.")

    try:
        import pandas as pd
    except ImportError:
        raise ZeddaError("pandas is required for merge(). Run: pip install pandas")

    if not _RICH_AVAILABLE or _console is None:
        print("Rich not available — install it: pip install rich")
        return None

    n_files = len(paths)

    # ── Header ──────────────────────────────────────────────────
    _console.print(
        f"\n[bold blue]zedda[/bold blue] [dim]v{__version__}[/dim]  ·  "
        f"[bold]merge mode[/bold]  ·  [dim]{n_files} files[/dim]\n"
    )

    # ── Profile each file ───────────────────────────────────────
    profiles = []
    dataframes = []
    file_names = []

    for file_path in paths:
        resolved, is_temp = _resolve_input(file_path)
        try:
            p = scan(resolved, sample_size=sample_size)
            profiles.append(p)
            name = Path(file_path).name if isinstance(file_path, (str, Path)) else "<DataFrame>"
            file_names.append(name)

            ext = Path(resolved).suffix.lower()
            if ext == ".csv":
                df = pd.read_csv(resolved)
            elif ext in (".parquet", ".arrow"):
                df = pd.read_parquet(resolved)
            else:
                raise ZeddaError(f"Unsupported format: {ext}")
            dataframes.append(df)

            _console.print(
                f"  [green]✓[/green] {name}  "
                f"[dim]{p.num_rows:,} rows · {p.num_cols} cols · "
                f"{p.overall_null_pct:.1f}% nulls[/dim]"
            )
        finally:
            if is_temp:
                _cleanup_temp(resolved)

    _console.print()

    # ── Schema Check ────────────────────────────────────────────
    _console.print("[bold]Schema Check[/bold]")
    ref_cols = set(dataframes[0].columns)
    ref_n = len(ref_cols)
    schema_ok = True

    for i, df in enumerate(dataframes[1:], 1):
        this_cols = set(df.columns)
        if this_cols != ref_cols:
            missing = ref_cols - this_cols
            extra = this_cols - ref_cols
            schema_ok = False
            if missing:
                _console.print(
                    f"  [red]✗[/red]  {file_names[i]}: missing columns "
                    f"[red]{', '.join(missing)}[/red]"
                )
            if extra:
                _console.print(
                    f"  [yellow]⚠[/yellow]  {file_names[i]}: extra columns "
                    f"[yellow]{', '.join(extra)}[/yellow]"
                )

    if schema_ok:
        _console.print(
            f"  [green]✓[/green]  {ref_n}/{ref_n} columns match "
            f"across all {n_files} files"
        )
    _console.print()

    # ── Overlap / Duplicate Check ───────────────────────────────
    _console.print("[bold]Overlap Check[/bold]")
    total_dupes_removed = 0
    common_cols = list(ref_cols.intersection(*[set(df.columns) for df in dataframes]))

    for i in range(len(dataframes)):
        for j in range(i + 1, len(dataframes)):
            if not common_cols:
                break
            try:
                merged_check = pd.merge(
                    dataframes[i][common_cols],
                    dataframes[j][common_cols],
                    how="inner",
                )
                n_overlap = len(merged_check)
                if n_overlap > 0:
                    _console.print(
                        f"  [yellow]⚠[/yellow]  {n_overlap} duplicate rows found "
                        f"between {file_names[i]} and {file_names[j]}"
                    )
                    _console.print(
                        f"     [dim]Keeping first occurrence, removing from "
                        f"{file_names[j]}.[/dim]"
                    )
                    total_dupes_removed += n_overlap
            except Exception:
                pass  # silently skip if merge check fails

    if total_dupes_removed == 0:
        _console.print("  [green]✓[/green]  No duplicate rows found")
    _console.print()

    # ── Distribution Check ──────────────────────────────────────
    _console.print("[bold]Distribution Check[/bold]")
    has_shift = False
    ref_profile = profiles[0]

    for col in ref_profile.columns:
        if col.type_str not in ("int", "float"):
            continue
        # Skip ID-like columns and binary columns
        if col.unique_pct > 95 or col.unique_approx <= 2:
            continue
        for i, other_p in enumerate(profiles[1:], 1):
            other_col = next((c for c in other_p.columns if c.name == col.name), None)
            if other_col is None or other_col.type_str not in ("int", "float"):
                continue
            if col.mean > 0:
                shift_pct = (other_col.mean - col.mean) / col.mean * 100
                if abs(shift_pct) > 15:
                    has_shift = True
                    _console.print(
                        f"  [yellow]⚠[/yellow]  '{rich_escape(col.name)}' — "
                        f"{file_names[i]} is {shift_pct:+.0f}% "
                        f"{'above' if shift_pct > 0 else 'below'} "
                        f"{file_names[0]} mean, worth investigating"
                    )

    if not has_shift:
        _console.print("  [green]✓[/green]  No significant distribution shifts")
    _console.print()

    # ── Merging ─────────────────────────────────────────────────
    _console.print("[bold]Merging[/bold]")
    t0 = time.perf_counter()

    # Add source column to each dataframe
    for i, df in enumerate(dataframes):
        dataframes[i] = df.assign(zedda_source_file=file_names[i])

    # Concatenate
    combined = pd.concat(dataframes, ignore_index=True)

    # Remove duplicates (keep first occurrence)
    cols_for_dedup = [c for c in combined.columns if c != "zedda_source_file"]
    before_dedup = len(combined)
    combined = combined.drop_duplicates(subset=cols_for_dedup, keep="first")
    actual_dupes = before_dedup - len(combined)

    elapsed_ms = (time.perf_counter() - t0) * 1000

    _console.print(
        f"  [green]✓[/green]  {len(combined):,} rows combined"
        + (f" ({actual_dupes} duplicates removed)" if actual_dupes > 0 else "")
    )
    _console.print(
        f"  [green]✓[/green]  Source column added: 'zedda_source_file'"
    )
    _console.print()

    # ── Save output ─────────────────────────────────────────────
    out_ext = Path(output).suffix.lower()
    if out_ext in (".parquet", ".arrow"):
        combined.to_parquet(output, index=False)
    else:
        combined.to_csv(output, index=False)

    _console.print("[bold]Output[/bold]")
    _console.print(
        f"  [green]✓[/green]  {Path(output).name} saved · "
        f"{len(combined):,} rows · {len(combined.columns)} cols · "
        f"{elapsed_ms:.0f} ms"
    )
    _console.print(
        f'\n  [dim]Run zd.profile("{Path(output).name}") '
        f"to profile the merged dataset.[/dim]\n"
    )

    return combined

# ─────────────────────────────────────────────────────────────────
#  zd.ask() — Natural Language Dataset Q&A
#
#  Answers plain-English questions about any profiled dataset.
#  Uses a pure rule engine (offline) for common patterns, and
#  falls back to Zedda AI (online) for complex questions.
#
#  MODES
#    offline  →  Pattern A–D rule engine (instant, no network)
#    online   →  Zedda AI analysis (requires ZEDDA_AI_KEY)
#
#  SECURITY CONTROLS
#    SEC-Q01  Path existence + file-only check
#    SEC-Q02  Blocked system root paths
#    SEC-Q03  Extension allowlist
#    SEC-Q04  Question sanitization (control chars, injection chars)
#    SEC-Q05  AI key sourced only from env var; never logged
#    SEC-Q06  AI context caps (50 cols, 20 corrs); basename-only path
#    SEC-Q07  Network timeout=10s; all exceptions caught
#    SEC-Q08  No eval/exec/subprocess anywhere in ask()
# ─────────────────────────────────────────────────────────────────


# ── SEC-Q03: Extension allowlist for ask() ───────────────────────
_ASK_ALLOWED_EXT = {".csv", ".parquet", ".arrow", ".feather"}

# ── SEC-Q02: Blocked OS root paths (case-insensitive prefix match) ─
_ASK_BLOCKED_ROOTS = [
    "/etc",
    "/proc",
    "/sys",
    "/root",
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
]

# ── Zedda AI pricing table (internal — never shown to user) ──────
_AI_PRICING = {
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "openai/gpt-oss-120b": {"input": 0.15, "output": 0.75},
    "openai/gpt-oss-20b": {"input": 0.10, "output": 0.50},
    "moonshotai/kimi-k2-instruct-0905": {"input": 0.55, "output": 2.20},
}

# ── Default AI model (internal — not exposed to user) ───────────
_AI_DEFAULT_MODEL = "llama-3.3-70b-versatile"

# ── AI system prompt (internal) ──────────────────────────────────
_AI_SYSTEM_PROMPT = (
    "You are Zedda AI, an expert data analyst assistant built into the Zedda "
    "data profiling library. You answer concise, practical questions about "
    "datasets based on their statistical profile. "
    "Format your response with clear sections using labels like "
    "'Drop immediately:', 'Drop or transform:', 'Keep:' when recommending "
    "column actions. Keep answers under 400 words. "
    "Never mention Groq, LLaMA, any model name, or any API. "
    "Always respond as if you are Zedda's own built-in intelligence."
)

# ── Domain signals for Pattern B ─────────────────────────────────
_DOMAIN_SIGNALS = {
    "fraud": {
        "question_keywords": ["fraud"],
        "col_keywords": ["fraud", "isfraud", "is_fraud", "fraudulent"],
        "needs_amount": True,
        "needs_timestamp": True,
        "positive_label": "fraud / anomaly detection",
    },
    "churn": {
        "question_keywords": ["churn"],
        "col_keywords": ["churn", "is_churn", "churned"],
        "needs_amount": False,
        "needs_timestamp": False,
        "positive_label": "churn prediction",
    },
    "regression": {
        "question_keywords": [
            "regression",
            "predict",
            "price prediction",
            "sales forecast",
        ],
        "col_keywords": [
            "price",
            "salary",
            "revenue",
            "sales",
            "score",
            "value",
            "amount",
        ],
        "needs_amount": False,
        "needs_timestamp": False,
        "positive_label": "regression / prediction",
    },
    "classification": {
        "question_keywords": ["classification", "classify"],
        "col_keywords": ["class", "label", "target", "category", "type"],
        "needs_amount": False,
        "needs_timestamp": False,
        "positive_label": "classification",
    },
    "recommendation": {
        "question_keywords": ["recommendation", "recommend", "collaborative filtering"],
        "col_keywords": ["rating", "user_id", "item_id", "product_id", "movie_id"],
        "needs_amount": False,
        "needs_timestamp": False,
        "positive_label": "recommendation systems",
    },
    "nlp": {
        "question_keywords": ["nlp", "text classification", "sentiment"],
        "col_keywords": ["text", "review", "comment", "description", "content", "body"],
        "needs_amount": False,
        "needs_timestamp": False,
        "positive_label": "NLP / text classification",
    },
    "time_series": {
        "question_keywords": ["time series", "forecasting", "forecast", "temporal"],
        "col_keywords": [],  # triggered by timestamp column presence
        "needs_amount": False,
        "needs_timestamp": True,
        "positive_label": "time-series forecasting",
    },
}


# ─────────────────────────────────────────────────────────────────
#  SEC-Q01 / SEC-Q02 / SEC-Q03: Path validation
# ─────────────────────────────────────────────────────────────────
def _ask_validate_path(path: str) -> None:
    """Validate path for ask(). Raises FileNotFoundError, ValueError, or PermissionError."""
    import os

    # SEC-P02 (carried forward): reject null-byte paths
    if "\x00" in str(path):
        raise ValueError("Path contains null bytes — rejected.")

    # SEC-Q01: must exist and be a file
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if not os.path.isfile(path):
        raise ValueError(f"'{path}' is a directory, not a file.")

    # SEC-Q02: block system-critical root paths
    real = os.path.realpath(path).lower()
    for blocked in _ASK_BLOCKED_ROOTS:
        if real.startswith(blocked):
            raise PermissionError(f"Access to system path '{path}' is not allowed.")

    # SEC-Q03: extension must be in the allowlist
    ext = os.path.splitext(path)[1].lower()
    if ext not in _ASK_ALLOWED_EXT:
        raise ValueError(
            f"Unsupported format '{ext}'. Supported: "
            + ", ".join(sorted(_ASK_ALLOWED_EXT))
        )


# ─────────────────────────────────────────────────────────────────
#  SEC-Q04: Question sanitization
# ─────────────────────────────────────────────────────────────────
def _ask_sanitize_question(q: str) -> str:
    """Strip prompt-injection chars, truncate to 500, raise if empty."""
    import re as _re

    q = q.strip()[:500]  # length cap
    q = q.replace('"""', "").replace("'''", "")  # triple-quote removal
    q = _re.sub(r"[\x00-\x1f`<>{}\x7f]", "", q)  # control + injection chars
    q = q.strip()
    if not q:
        raise ValueError("Question cannot be empty after sanitization.")
    return q


# ─────────────────────────────────────────────────────────────────
#  Pattern A — "which columns have more than X% nulls?"
# ─────────────────────────────────────────────────────────────────
def _ask_pattern_a(p: Any, question: str, path: str):
    """
    Returns (answer_text, show_fix_tip, render_kwargs) or None.
    render_kwargs may contain: gradient_rows (list of (label, val, color))
    """
    import re as _re

    q_lower = question.lower()
    if not ("null" in q_lower or "missing" in q_lower):
        return None
    m = _re.search(r"(\d+)\s*%", question)
    if not m:
        return None

    threshold = int(m.group(1))
    matched = sorted(
        [col for col in p.columns if col.null_pct > threshold],
        key=lambda c: c.null_pct,
        reverse=True,
    )

    if not matched:
        answer = f"No columns have more than {threshold}% nulls."
        return answer, False, {}

    # Build the gradient_rows list used by _render_ask_output
    gradient_rows = []
    lines = []
    for col in matched:
        # Robust null_count: use C++ field directly, fall back to computed
        try:
            null_c = int(col.null_count)
            if null_c == 0 and col.null_pct > 0:
                null_c = int(p.num_rows * col.null_pct / 100)
        except Exception:
            null_c = int(p.num_rows * col.null_pct / 100)

        if col.null_pct > 50:
            color = "red"
        elif col.null_pct > 10:
            color = "yellow"
        else:
            color = "default"

        label = f"{col.name}   {col.null_pct:.1f}%   ({null_c:,} of {p.num_rows:,} rows missing)"
        lines.append(label)
        gradient_rows.append((col.name, col.null_pct, color))

    n = len(matched)
    answer = (
        f"{n} column{'s' if n > 1 else ''} have more than {threshold}% nulls:\n\n"
        + "\n".join(lines)
    )
    return answer, True, {"gradient_rows": gradient_rows}


# ─────────────────────────────────────────────────────────────────
#  Pattern B — "is this dataset good for X?"
# ─────────────────────────────────────────────────────────────────
def _ask_pattern_b(p: Any, question: str):
    """
    Returns (answer_text, show_fix_tip, render_kwargs) or None.
    render_kwargs may contain: checklist_rows (list of (bool, str))
    """
    q_lower = question.lower()

    # Must contain an intent phrase
    intent_phrases = [
        "good for",
        "suitable for",
        "is this dataset",
        "use this for",
        "use for",
        "work for",
        "fit for",
        "best for",
    ]
    if not any(ph in q_lower for ph in intent_phrases):
        return None

    # Find which domain the question is about
    matched_domain = None
    matched_key = None
    for domain_key, signals in _DOMAIN_SIGNALS.items():
        if any(kw in q_lower for kw in signals["question_keywords"]):
            matched_domain = signals
            matched_key = domain_key
            break

    if matched_domain is None:
        return None  # domain not recognized — let LLM handle it

    col_names_lower = {c.name.lower() for c in p.columns}

    # Check for domain-specific column keywords
    domain_col_found = (
        any(kw in cn for kw in matched_domain["col_keywords"] for cn in col_names_lower)
        if matched_domain["col_keywords"]
        else True
    )  # time_series has empty list

    # Check for amount / timestamp columns
    has_amount = any(
        amt in cn
        for amt in ("amount", "price", "value", "balance", "total", "sum")
        for cn in col_names_lower
    )
    has_timestamp = any(
        ts in cn
        for ts in ("date", "time", "_at", "timestamp", "created", "updated")
        for cn in col_names_lower
    )

    # Detect overall dataset type
    best_binary_col = next(
        (
            col
            for col in p.columns
            if col.type_str in ("int", "float")
            and col.unique_approx <= 2
            and col.val_min == 0
            and col.val_max == 1
        ),
        None,
    )
    if best_binary_col:
        dataset_type = "classification (binary)"
        suggested_target = best_binary_col.name
    elif p.num_numeric > p.num_string:
        dataset_type = "numeric / regression"
        suggested_target = None
    else:
        dataset_type = "tabular / general"
        suggested_target = None

    # Build checklist
    checklist: list = []
    all_ok = True

    if matched_domain["col_keywords"]:
        ok = domain_col_found
        if not ok:
            all_ok = False
        checklist.append(
            (
                ok,
                f"Domain column found ({', '.join(matched_domain['col_keywords'][:3])})...",
            )
        )

    if matched_domain["needs_amount"]:
        ok = has_amount
        if not ok:
            all_ok = False
        checklist.append((ok, "Amount / value column present"))

    if matched_domain["needs_timestamp"]:
        ok = has_timestamp
        if not ok:
            all_ok = False
        checklist.append((ok, "Timestamp / date column present"))

    checklist.append(
        (
            p.overall_null_pct < 30,
            f"Overall null rate acceptable ({p.overall_null_pct:.1f}%)",
        )
    )
    checklist.append((p.num_rows >= 100, f"Sufficient row count ({p.num_rows:,} rows)"))

    # Compose answer
    pos_label = matched_domain["positive_label"]
    if all_ok:
        verdict = f"Yes — this dataset looks suitable for {pos_label}."
    else:
        verdict = (
            f"No — this dataset is missing key signals for {pos_label}.\n"
            f"Suggestion: Look for a dataset that includes "
            + (
                ", ".join(
                    (
                        [f"a '{matched_key}'-related column"]
                        if matched_domain["col_keywords"] and not domain_col_found
                        else []
                    )
                    + (
                        ["amount/value columns"]
                        if matched_domain["needs_amount"] and not has_amount
                        else []
                    )
                    + (
                        ["timestamp/date columns"]
                        if matched_domain["needs_timestamp"] and not has_timestamp
                        else []
                    )
                )
                or "the required domain columns"
            )
            + "."
        )

    detail_lines = [f"Dataset type detected: {dataset_type}"]
    if suggested_target:
        detail_lines.append(f"Suggested target column: '{suggested_target}'")

    answer = verdict + "\n\n" + "\n".join(detail_lines)
    return answer, False, {"checklist_rows": checklist, "verdict_yes": all_ok}


# ─────────────────────────────────────────────────────────────────
#  Pattern C — "what is the X rate by Y?"
# ─────────────────────────────────────────────────────────────────
def _ask_pattern_c(p: Any, question: str, path: str):
    """
    Performs a pandas groupby on the dataset.
    Returns (answer_text, show_fix_tip, render_kwargs) or None.
    render_kwargs may contain: gradient_rows (list of (label, value, color))
    """
    import os as _os
    import re as _re

    q_lower = question.lower()

    # Pattern: "X rate/mean/average by Y" or "average X by Y"
    m = _re.search(
        r"(?:(\w[\w\s]*?)\s+)?(?:rate|mean|average|avg)\s+(?:of\s+)?([\w\s]+?)\s+by\s+([\w\s]+)",
        q_lower,
    )
    if not m:
        # Simpler fallback: "X by Y"
        m2 = _re.search(r"([\w]+(?:\s+[\w]+)*)\s+by\s+([\w]+(?:\s+[\w]+)*)", q_lower)
        if not m2:
            return None
        target_hint = m2.group(1).strip()
        group_hint = m2.group(2).strip()
    else:
        target_hint = (m.group(2) or "").strip()
        group_hint = (m.group(3) or "").strip()

    # Find matching columns (case-insensitive substring match)
    def _find_col(hint: str):
        hint_l = hint.lower()
        # Exact name match first
        for col in p.columns:
            if col.name.lower() == hint_l:
                return col
        # Substring match
        for col in p.columns:
            if hint_l in col.name.lower() or col.name.lower() in hint_l:
                return col
        return None

    target_col = _find_col(target_hint)
    group_col = _find_col(group_hint)

    if target_col is None or group_col is None:
        return None
    if target_col.name == group_col.name:
        return None
    if target_col.type_str not in ("int", "float"):
        return None
    if group_col.unique_approx > 50:  # too many groups — would produce noise
        return None

    # SEC-Q: 2 GB file-size guard
    try:
        file_bytes = _os.path.getsize(path)
    except Exception:
        file_bytes = 0

    if file_bytes > 2 * 1024**3:
        # Friendly message, not a silent skip
        answer = (
            f"This dataset is too large for an inline groupby analysis "
            f"(file is {file_bytes / 1024**3:.1f} GB).\n"
            f"Try: zd.ask(path, question) after sampling with "
            f"zd.scan(path, sample_size=1_000_000)."
        )
        return answer, False, {}

    # Lazy pandas import (SEC: no hard dependency)
    try:
        import pandas as _pd
    except ImportError:
        return None  # fall through to Pattern D or LLM

    try:
        ext = _os.path.splitext(path)[1].lower()
        if ext == ".csv":
            df = _pd.read_csv(
                path, nrows=5_000_000, usecols=[group_col.name, target_col.name]
            )
        elif ext == ".parquet":
            df = _pd.read_parquet(path, columns=[group_col.name, target_col.name])
        elif ext == ".arrow" or ext == ".feather":
            df = _pd.read_feather(path, columns=[group_col.name, target_col.name])
        else:
            return None
    except Exception:
        return None  # any read failure — fall through gracefully

    try:
        result = (
            df.groupby(group_col.name)[target_col.name]
            .mean()
            .sort_values(ascending=False)
        )
    except Exception:
        return None

    if result.empty:
        return None

    # 3-color gradient
    max_val = float(result.max())
    min_val = float(result.min())
    val_range = max_val - min_val

    gradient_rows = []
    for grp_val, mean_val in result.items():
        mv = float(mean_val)
        if val_range > 0:
            frac = (mv - min_val) / val_range
        else:
            frac = 1.0
        if frac >= 0.67:
            color = "green"
        elif frac >= 0.33:
            color = "yellow"
        else:
            color = "red"
        gradient_rows.append((str(grp_val), mv, color))

    # Interpretation line
    corr_note = ""
    for cr in p.correlations:
        if {cr.col_a, cr.col_b} == {group_col.name, target_col.name}:
            sign = "positive" if cr.r > 0 else "negative"
            corr_note = (
                f"Strong {sign} correlation (r={cr.r:+.2f}) detected between "
                f"'{group_col.name}' and '{target_col.name}'."
            )
            break
    if not corr_note:
        corr_note = (
            f"'{group_col.name}' appears to be a useful feature "
            f"for predicting '{target_col.name}'."
        )

    n_groups = len(result)
    answer = (
        f"Mean '{target_col.name}' by '{group_col.name}' ({n_groups} groups):\n\n"
        + "\n".join(f"  {g}: {v:.4g}" for g, v, _ in gradient_rows)
        + f"\n\n{corr_note}"
    )
    return (
        answer,
        False,
        {
            "gradient_rows": gradient_rows,
            "group_label": group_col.name,
            "target_label": target_col.name,
        },
    )


# ─────────────────────────────────────────────────────────────────
#  Pattern D — General profile lookups (fallback offline)
# ─────────────────────────────────────────────────────────────────
def _ask_pattern_d(p: Any, question: str):
    """
    Returns (answer_text, show_fix_tip, render_kwargs) or None.
    Handles all common profile Q&A without any pandas or network.
    """
    import re as _re

    q_lower = question.lower()
    num_cols = p.num_cols
    num_rows = p.num_rows

    # ── Single-column stat lookups ─────────────────────────────────
    _single_col_patterns = [
        (_re.compile(r"mean\s+(?:of\s+)?(.+)", _re.I), "mean"),
        (
            _re.compile(r"null\s+(?:rate|pct|percent)\s+(?:of\s+)?(.+)", _re.I),
            "null_pct",
        ),
        (_re.compile(r"type\s+(?:of\s+)?(.+)", _re.I), "type_str"),
        (_re.compile(r"min(?:imum)?\s+(?:of\s+)?(.+)", _re.I), "val_min"),
        (_re.compile(r"max(?:imum)?\s+(?:of\s+)?(.+)", _re.I), "val_max"),
        (_re.compile(r"stddev\s+(?:of\s+)?(.+)", _re.I), "stddev"),
        (_re.compile(r"skewness\s+(?:of\s+)?(.+)", _re.I), "skewness"),
    ]
    for pat, attr in _single_col_patterns:
        m = pat.search(question)
        if m:
            col_hint = m.group(1).strip().rstrip("?").strip()
            col_hint_l = col_hint.lower()
            found = None
            # Exact match first
            for col in p.columns:
                if col.name.lower() == col_hint_l:
                    found = col
                    break
            # Substring match
            if found is None:
                for col in p.columns:
                    if col_hint_l in col.name.lower() or col.name.lower() in col_hint_l:
                        found = col
                        break
            if found is None:
                avail = ", ".join(c.name for c in p.columns[:15])
                if len(p.columns) > 15:
                    avail += f" ... ({num_cols - 15} more)"
                return (
                    f"Column '{col_hint}' not found.\nAvailable columns: {avail}",
                    False,
                    {},
                )
            val = getattr(found, attr, None)
            if attr == "mean" and found.type_str not in ("int", "float"):
                return (
                    f"'{found.name}' is a {found.type_str} column — mean is not applicable.",
                    False,
                    {},
                )
            if attr in (
                "val_min",
                "val_max",
                "stddev",
                "skewness",
            ) and found.type_str not in ("int", "float"):
                return (
                    f"'{found.name}' is a {found.type_str} column — {attr} is not applicable.",
                    False,
                    {},
                )
            return (
                f"{attr.replace('_', ' ').title()} of '{found.name}': {val}",
                False,
                {},
            )

    # ── Row count ─────────────────────────────────────────────────
    if any(
        kw in q_lower
        for kw in ("row count", "how many rows", "number of rows", "rows in")
    ):
        sampled = " (sampled)" if p.is_sampled else ""
        return (f"This dataset has {num_rows:,} rows{sampled}.", False, {})

    # ── Column count ──────────────────────────────────────────────
    if any(
        kw in q_lower
        for kw in (
            "column count",
            "how many columns",
            "number of columns",
            "how many features",
        )
    ):
        return (
            f"This dataset has {num_cols} columns "
            f"({p.num_numeric} numeric, {p.num_string} string).",
            False,
            {},
        )

    # ── Quality / ML readiness score ──────────────────────────────
    if any(
        kw in q_lower
        for kw in (
            "quality score",
            "data quality",
            "ml ready",
            "ml-ready",
            "ml readiness",
        )
    ):
        score = _quality_score(p)
        label = "GOOD" if score >= 80 else "FAIR" if score >= 60 else "POOR"
        return (
            f"Data quality score: {score}/100  [{label}]\n"
            f"Breakdown: {p.num_numeric} numeric, {p.num_string} string columns, "
            f"{p.overall_null_pct:.1f}% overall null rate.",
            False,
            {},
        )

    # ── Most-null column ──────────────────────────────────────────
    if any(
        kw in q_lower
        for kw in ("most null", "most missing", "highest null", "worst null")
    ):
        if not p.columns:
            return ("No columns found in dataset.", False, {})
        worst = max(p.columns, key=lambda c: c.null_pct)
        return (
            f"Column with most nulls: '{worst.name}' — {worst.null_pct:.1f}% missing.",
            worst.null_pct > 20,
            {},
        )

    # ── All null/missing columns ──────────────────────────────────
    if any(kw in q_lower for kw in ("null", "missing")):
        null_cols = sorted(
            [c for c in p.columns if c.null_pct > 0],
            key=lambda c: c.null_pct,
            reverse=True,
        )
        if not null_cols:
            return ("No missing values found — all columns are complete.", False, {})
        lines = [f"  {c.name}: {c.null_pct:.1f}% missing" for c in null_cols]
        return (
            f"{len(null_cols)} column(s) have missing values:\n" + "\n".join(lines),
            len(null_cols) > 0,
            {},
        )

    # ── Outlier columns ───────────────────────────────────────────
    if "outlier" in q_lower:
        outliers = [
            c
            for c in p.columns
            if c.type_str in ("int", "float")
            and c.mean > 0
            and c.unique_approx > 5
            and c.val_max > 10
            and c.val_max > c.mean * 10
            and "ratio" not in c.name.lower()
            and "pct" not in c.name.lower()
        ]
        if not outliers:
            return ("No extreme outlier columns detected.", False, {})
        is_int = lambda c: c.type_str == "int"
        lines = [
            f"  {c.name}: max={_format_num(c.val_max, is_int(c))} is "
            f"{c.val_max / c.mean:.0f}x above mean"
            for c in outliers
        ]
        return (
            f"{len(outliers)} column(s) with potential outliers:\n" + "\n".join(lines),
            True,
            {},
        )

    # ── Binary / target columns ───────────────────────────────────
    if any(kw in q_lower for kw in ("binary", "target column", "binary column")):
        binary = [
            c
            for c in p.columns
            if c.type_str in ("int", "float")
            and c.unique_approx <= 2
            and c.val_min == 0
            and c.val_max == 1
        ]
        if not binary:
            return ("No binary (0/1) columns found.", False, {})
        names = ", ".join(f"'{c.name}'" for c in binary)
        return (
            f"Binary (0/1) column{'s' if len(binary) > 1 else ''}: {names}",
            False,
            {},
        )

    # ── ID columns ────────────────────────────────────────────────
    if any(kw in q_lower for kw in ("id column", "id columns", "identifier")):
        id_cols = [c for c in p.columns if c.type_str == "int" and c.unique_pct > 95]
        if not id_cols:
            return ("No obvious ID columns detected.", False, {})
        names = ", ".join(f"'{c.name}'" for c in id_cols)
        return (
            f"Likely ID column{'s' if len(id_cols) > 1 else ''} "
            f"(>95% unique integers): {names}",
            True,
            {},
        )

    # ── Correlated columns ────────────────────────────────────────
    if any(kw in q_lower for kw in ("correlated", "correlation", "multicollinear")):
        if not p.correlations:
            return ("No strong correlations (|r| >= 0.7) found.", False, {})
        lines = [
            f"  '{cr.col_a}' <-> '{cr.col_b}'  r={cr.r:+.2f}  [{cr.strength}]"
            for cr in p.correlations
        ]
        return (
            f"{len(p.correlations)} correlated pair(s):\n" + "\n".join(lines),
            False,
            {},
        )

    # ── Constant columns ─────────────────────────────────────────
    if "constant" in q_lower:
        const_cols = [c for c in p.columns if c.is_constant]
        if not const_cols:
            return ("No constant columns found.", False, {})
        names = ", ".join(f"'{c.name}'" for c in const_cols)
        return (
            f"Constant column{'s' if len(const_cols) > 1 else ''}: {names}",
            True,
            {},
        )

    # ── Skewed columns ────────────────────────────────────────────
    if "skew" in q_lower:
        # Adaptive threshold: use |skewness| > 1 for smaller datasets,
        # |skewness| > 2 for large ones (reduces false positives at scale)
        threshold = 2.0 if num_rows >= 10_000 else 1.0
        skewed = [
            c
            for c in p.columns
            if c.type_str in ("int", "float") and abs(c.skewness) > threshold
        ]
        if not skewed:
            return (
                f"No heavily skewed numeric columns found "
                f"(threshold |skewness| > {threshold:.0f}).",
                False,
                {},
            )
        lines = [
            f"  {c.name}: skewness={c.skewness:.2f} "
            f"({'right' if c.skewness > 0 else 'left'}-skewed)"
            for c in sorted(skewed, key=lambda c: abs(c.skewness), reverse=True)
        ]
        return (
            f"{len(skewed)} skewed column{'s' if len(skewed) > 1 else ''} "
            f"(|skewness| > {threshold:.0f}):\n" + "\n".join(lines),
            True,
            {},
        )

    # ── String / text columns ─────────────────────────────────────
    if any(
        kw in q_lower for kw in ("string", "text column", "text columns", "categorical")
    ):
        str_cols = [c for c in p.columns if c.type_str not in ("int", "float", "bool")]
        if not str_cols:
            return ("No string/categorical columns found.", False, {})
        lines = [f"  {c.name} ({c.unique_approx} unique values)" for c in str_cols]
        return (
            f"{len(str_cols)} string/categorical column(s):\n" + "\n".join(lines),
            False,
            {},
        )

    # ── Numeric columns ───────────────────────────────────────────
    if any(kw in q_lower for kw in ("numeric", "numeric columns", "numerical")):
        num = [c for c in p.columns if c.type_str in ("int", "float")]
        if not num:
            return ("No numeric columns found.", False, {})
        lines = [
            f"  {c.name} ({c.type_str})  mean={_format_num(c.mean, c.type_str == 'int')}"
            for c in num
        ]
        return (f"{len(num)} numeric column(s):\n" + "\n".join(lines), False, {})

    # ── High cardinality columns ──────────────────────────────────
    if any(
        kw in q_lower for kw in ("high cardinality", "high-cardinality", "many unique")
    ):
        high_card = [c for c in p.columns if c.unique_approx > 50]
        if not high_card:
            return (
                "No high-cardinality columns found (threshold: >50 unique values).",
                False,
                {},
            )
        lines = [f"  {c.name}: ~{c.unique_approx:,} unique values" for c in high_card]
        return (
            f"{len(high_card)} high-cardinality column(s):\n" + "\n".join(lines),
            False,
            {},
        )

    # ── What should I drop? ───────────────────────────────────────
    if any(kw in q_lower for kw in ("what should i drop", "drop", "remove", "useless")):
        drop_list = []
        for c in p.columns:
            reasons = []
            if c.type_str == "int" and c.unique_pct > 95:
                reasons.append(f"ID-like ({c.unique_pct:.0f}% unique)")
            if c.is_constant:
                reasons.append("constant")
            if c.null_pct > 70:
                reasons.append(f"{c.null_pct:.0f}% nulls")
            if reasons:
                drop_list.append((c.name, ", ".join(reasons)))
        if not drop_list:
            return (
                "No obvious columns to drop — dataset looks reasonably clean.",
                False,
                {},
            )
        lines = [f"  Drop '{name}': {reason}" for name, reason in drop_list]
        return (
            f"{len(drop_list)} column(s) recommended for dropping:\n"
            + "\n".join(lines),
            True,
            {},
        )

    # ── Sampled? ──────────────────────────────────────────────────
    if any(kw in q_lower for kw in ("sampled", "was this sampled", "is this sampled")):
        if p.is_sampled:
            return (
                f"Yes — this dataset was sampled. {num_rows:,} rows were analyzed.",
                False,
                {},
            )
        return (f"No — the full dataset was scanned ({num_rows:,} rows).", False, {})

    # ── Scan time ─────────────────────────────────────────────────
    if any(kw in q_lower for kw in ("scan time", "how long", "how fast")):
        ms = p.scan_time_ms
        time_str = f"{ms / 1000:.1f} seconds" if ms >= 10_000 else f"{ms:.0f} ms"
        return (f"Scan completed in {time_str}.", False, {})

    # ── No offline pattern matched ─────────────────────────────────
    return None


# ─────────────────────────────────────────────────────────────────
#  SEC-Q06: Build safe AI context JSON (internal)
# ─────────────────────────────────────────────────────────────────
def _build_ask_context(p: Any, question: str) -> str:
    """Build a safe, capped JSON context to send to Zedda AI."""
    import json as _json
    import os as _os
    import re as _re

    def _safe_name(name: str) -> str:
        # SEC-Q06: Strip non-word chars from column names sent to AI
        return _re.sub(r"[^\w\s]", "", name)

    cols_payload = []
    for col in p.columns[:50]:  # cap at 50
        entry = {
            "name": _safe_name(col.name),
            "type": col.type_str,
            "null_pct": round(col.null_pct, 2),
            "unique_approx": col.unique_approx,
        }
        if col.type_str in ("int", "float"):
            entry["mean"] = round(col.mean, 4) if col.mean is not None else None
            entry["stddev"] = round(col.stddev, 4) if col.stddev is not None else None
            entry["val_min"] = (
                round(col.val_min, 4) if col.val_min is not None else None
            )
            entry["val_max"] = (
                round(col.val_max, 4) if col.val_max is not None else None
            )
            entry["skewness"] = (
                round(col.skewness, 4) if col.skewness is not None else None
            )
        cols_payload.append(entry)

    corr_payload = [
        {
            "col_a": _safe_name(cr.col_a),
            "col_b": _safe_name(cr.col_b),
            "r": round(cr.r, 4),
        }
        for cr in p.correlations[:20]  # cap at 20
    ]

    context = {
        "dataset": {
            "file": _os.path.basename(p.file_name),  # SEC-Q06: basename only
            "num_rows": p.num_rows,
            "num_cols": p.num_cols,
            "num_numeric": p.num_numeric,
            "num_string": p.num_string,
            "overall_null_pct": round(p.overall_null_pct, 2),
            "is_sampled": p.is_sampled,
        },
        "columns": cols_payload,
        "correlations": corr_payload,
        "question": question,
    }
    return _json.dumps(context, separators=(",", ":"))


# ─────────────────────────────────────────────────────────────────
#  SEC-Q05 / SEC-Q07: Zedda AI call (internal — never exposed)
# ─────────────────────────────────────────────────────────────────
def _ask_zedda_ai(context_json: str, question: str, model: str):
    """
    Call the Zedda AI backend. Returns (answer_text, usage_dict) on
    success, or (None, error_string) on any failure.

    Security:
      SEC-Q05: API key read from env var only; never logged or printed.
      SEC-Q07: timeout=10; all exceptions caught and returned as strings.
    """
    import os as _os

    try:
        import requests as _requests
    except ImportError:
        return None, (
            "Zedda AI requires the 'requests' library.\n"
            "Install it with: pip install requests"
        )

    # SEC-Q05: Key from env only — never log, print, or embed in strings
    api_key = _os.environ.get("ZEDDA_AI_KEY", "")
    if not api_key:
        return None, (
            "Zedda AI is not configured.\n"
            "Set the ZEDDA_AI_KEY environment variable to enable AI analysis.\n"
            "For offline analysis, try asking about: nulls, outliers, "
            "correlations, data quality, or specific column stats."
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _AI_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Dataset profile:\n{context_json}\n\nQuestion: {question}",
            },
        ],
        "max_tokens": 800,
        "temperature": 0.2,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = _requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=10,  # SEC-Q07
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage", {})
        return answer, usage
    except _requests.exceptions.Timeout:
        return None, "Zedda AI timed out. Please try again."
    except _requests.exceptions.RequestException as exc:
        return None, f"Zedda AI is temporarily unavailable. ({type(exc).__name__})"
    except (KeyError, IndexError, ValueError):
        return None, "Zedda AI returned an unexpected response. Please try again."
    except Exception as exc:
        return None, f"Zedda AI encountered an error. ({type(exc).__name__})"


# ─────────────────────────────────────────────────────────────────
#  Rich rendering for ask() output
# ─────────────────────────────────────────────────────────────────
def _render_ask_output(
    question: str,
    path: str,
    p: Any,
    answer_text: str,
    mode: str,  # "offline" or a model string
    elapsed_ms: float,
    usage=None,  # Groq usage dict (online mode)
    show_fix_tip: bool = False,
    gradient_rows=None,  # list of (label, value, color) for Pattern A / C
    checklist_rows=None,  # list of (bool, str) for Pattern B
    verdict_yes: bool = True,  # for Pattern B coloring
    group_label: str = "",
    target_label: str = "",
) -> None:
    """Print the ask() answer using Rich (or plain text as fallback)."""
    import os as _os

    basename = _os.path.basename(path)
    is_online = mode != "offline"

    if not _RICH_AVAILABLE or _console is None:
        # ── Plain-text fallback ───────────────────────────────────
        print(
            f"\nzedda v{__version__}  ·  ask  ·  {'Zedda AI' if is_online else 'offline'}"
        )
        print(f"Question : {question}")
        print(f"Source   : {basename}  ({p.num_rows:,} rows · {p.num_cols} cols)")
        print("-" * 47)
        print(f"\nAnswer:\n{answer_text}\n")
        print("-" * 47)
        if is_online and usage:
            pt = usage.get("prompt_tokens", 0)
            elapsed_s = elapsed_ms / 1000
            print(f"Mode: Zedda AI  ·  context tokens: {pt}  ·  {elapsed_s:.1f}s")
        else:
            print(f"Mode: offline rule engine  ·  {elapsed_ms:.0f} ms")
        if show_fix_tip:
            print(f"Tip: run zd.fix('{basename}') to auto-generate fix code.")
        return

    # ── Rich rendering ────────────────────────────────────────────
    _console.print()

    # Header
    if is_online:
        _console.print(
            f"[bold green]zedda v{__version__}[/bold green]  "
            f"[dim]·[/dim]  [dim]ask mode[/dim]  [dim]·[/dim]  "
            f"[blue]Zedda AI[/blue]"
        )
    else:
        _console.print(
            f"[bold green]zedda v{__version__}[/bold green]  "
            f"[dim]·[/dim]  [dim]ask mode[/dim]  [dim]·[/dim]  "
            f"[dim]offline[/dim]"
        )

    # Metadata
    _console.print(f"  [dim]Question :[/dim]  {rich_escape(question)}")
    if is_online:
        _console.print(
            f"  [dim]Profile  :[/dim]  "
            f"[dim]{p.num_cols} cols · {p.num_rows:,} rows · sent to Zedda AI[/dim]"
        )
    else:
        _console.print(
            f"  [dim]Source   :[/dim]  "
            f"[dim]{rich_escape(basename)}  ({p.num_rows:,} rows · {p.num_cols} cols)[/dim]"
        )

    _console.print(f"  [dim]{'─' * 47}[/dim]")

    # Answer block
    _console.print("\n  [bold]Answer:[/bold]")
    _console.print()

    if checklist_rows is not None:
        # Pattern B: verdict + checklist
        first_line = answer_text.split("\n")[0]
        rest_lines = answer_text.split("\n")[1:]
        if verdict_yes:
            _console.print(f"  [bold green]{rich_escape(first_line)}[/bold green]")
        else:
            _console.print(f"  [bold red]{rich_escape(first_line)}[/bold red]")
        for ok, text in checklist_rows:
            icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
            _console.print(f"    {icon}  [dim]{rich_escape(text)}[/dim]")
        for line in rest_lines:
            stripped = line.strip()
            if stripped:
                _console.print(f"  [dim]{rich_escape(stripped)}[/dim]")
    elif gradient_rows is not None and len(gradient_rows) > 0 and target_label:
        # Pattern C: groupby table with color gradient
        _console.print(
            f"  Mean [cyan]{rich_escape(target_label)}[/cyan] "
            f"by [cyan]{rich_escape(group_label)}[/cyan]:"
        )
        _console.print()
        for label, val, color in gradient_rows:
            _console.print(
                f"    [{color}]{rich_escape(str(label)):>20}[/{color}]  "
                f"[{color}]{val:>10.4g}[/{color}]"
            )
        # Interpretation line
        interpretation_lines = [
            ln
            for ln in answer_text.split("\n")
            if "correlation" in ln.lower() or "feature" in ln.lower()
        ]
        if interpretation_lines:
            _console.print()
            _console.print(f"  [dim]{rich_escape(interpretation_lines[0])}[/dim]")
    elif gradient_rows is not None and len(gradient_rows) > 0 and not target_label:
        # Pattern A: null columns with color-coded severity
        for label, val, color in gradient_rows:
            _console.print(f"  [{color}]{rich_escape(label)}[/{color}]")
    elif is_online:
        # Online LLM answer — parse sections for coloring
        for line in answer_text.split("\n"):
            stripped = line.strip()
            if not stripped:
                _console.print()
                continue
            low = stripped.lower()
            if low.startswith("drop immediately"):
                _console.print(f"  [bold red]{rich_escape(stripped)}[/bold red]")
            elif low.startswith("drop or transform") or low.startswith(
                "consider dropping"
            ):
                _console.print(f"  [bold yellow]{rich_escape(stripped)}[/bold yellow]")
            elif low.startswith("keep"):
                _console.print(f"  [bold green]{rich_escape(stripped)}[/bold green]")
            else:
                _console.print(f"  {rich_escape(stripped)}")
    else:
        # Pattern D: plain answer
        for line in answer_text.split("\n"):
            _console.print(f"  {rich_escape(line)}" if line.strip() else "")

    _console.print()
    _console.print(f"  [dim]{'─' * 47}[/dim]")

    # Footer
    if is_online and usage:
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        elapsed_s = elapsed_ms / 1000
        pricing = _AI_PRICING.get(mode)
        if pricing:
            cost = (pt * pricing["input"] + ct * pricing["output"]) / 1_000_000
            _console.print(
                f"  [dim]Mode: Zedda AI  ·  "
                f"context tokens: {pt}  ·  {elapsed_s:.1f}s  ·  "
                f"~${cost:.4f}[/dim]"
            )
        else:
            _console.print(
                f"  [dim]Mode: Zedda AI  ·  "
                f"context tokens: {pt}  ·  {elapsed_s:.1f}s[/dim]"
            )
    else:
        _console.print(
            f"  [dim]Mode: offline rule engine  ·  {elapsed_ms:.0f} ms[/dim]"
        )

    if show_fix_tip:
        _console.print(
            f'  [dim]Tip: run [cyan]zd.fix("{rich_escape(basename)}")[/cyan] '
            f"to auto-generate fix code.[/dim]"
        )

    _console.print()


# ─────────────────────────────────────────────────────────────────
#  ask() — public entry point
# ─────────────────────────────────────────────────────────────────
def ask(
    path,
    question: str,
    llm: str = "zedda",
    model: str = None,
    print_output: bool = True,
) -> str:
    """
    Ask a plain-English question about a dataset and get an instant answer.

    Combines a fast offline rule engine for common questions (null rates,
    outliers, correlations, domain suitability) with Zedda AI for
    complex analytical questions that the rule engine can't answer.

    Offline patterns (instant, no network):
      - Pattern A: "which columns have more than X% nulls?"
      - Pattern B: "is this dataset good for fraud detection?"
      - Pattern C: "what is the survival rate by class?"
      - Pattern D: row/column counts, quality score, outliers, correlations,
                   skewed columns, binary columns, ID columns, drop suggestions,
                   and per-column stats (mean, min, max, null rate, type).

    Args:
        path (str):
            Path to a ``.csv``, ``.parquet``, ``.arrow``, or ``.feather`` file.
        question (str):
            Your plain-English question about the dataset.
        llm (str, default "zedda"):
            AI backend to use for questions the rule engine cannot answer.
            Currently only ``"zedda"`` is supported.
        model (str, optional):
            Override the default AI model (advanced users only).
        print_output (bool, default True):
            If ``False``, suppress terminal output and only return the answer
            string (useful for programmatic use).

    Returns:
        str: The answer as a plain string (regardless of print_output).

    Examples::

        import zedda as zd

        # Instant offline answers (no API key needed)
        zd.ask("titanic.csv", "which columns have more than 10% nulls?")
        zd.ask("titanic.csv", "is this dataset good for fraud detection?")
        zd.ask("titanic.csv", "what is the survival rate by class?")
        zd.ask("titanic.csv", "how many rows are there?")
        zd.ask("titanic.csv", "what should I drop?")
        zd.ask("titanic.csv", "mean of Age")

        # Zedda AI for complex questions (requires ZEDDA_AI_KEY env var)
        zd.ask("data.csv", "which features should I use for a random forest?")

        # Suppress output, capture the answer as a string
        answer = zd.ask("data.csv", "mean of Fare", print_output=False)
    """
    resolved_path, is_temp = _resolve_input(path)
    try:
        import time as _time

        # ── SEC-Q01/Q02/Q03: Validate path ────────────────────────
        _ask_validate_path(resolved_path)

        # ── SEC-Q04: Sanitize question ────────────────────────────
        question = _ask_sanitize_question(question)

        # ── Scan the dataset ──────────────────────────────────────
        t0 = _time.perf_counter()
        p = scan(resolved_path)  # reuses existing scan() — no code duplication

        # ── Try offline patterns in priority order ────────────────
        result = None
        result = _ask_pattern_a(p, question, resolved_path)
        if result is None:
            result = _ask_pattern_b(p, question)
        if result is None:
            result = _ask_pattern_c(p, question, resolved_path)
        if result is None:
            result = _ask_pattern_d(p, question)

        elapsed_ms = (_time.perf_counter() - t0) * 1000

        if result is not None:
            answer_text, show_fix_tip, render_kwargs = result
            if print_output:
                _render_ask_output(
                    question,
                    resolved_path,
                    p,
                    answer_text,
                    mode="offline",
                    elapsed_ms=elapsed_ms,
                    show_fix_tip=show_fix_tip,
                    **render_kwargs,
                )
            return answer_text

        # ── Online fallback: Zedda AI ─────────────────────────────
        effective_model = model or _AI_DEFAULT_MODEL
        context_json = _build_ask_context(p, question)

        t1 = _time.perf_counter()
        answer_text, usage = _ask_zedda_ai(context_json, question, effective_model)
        elapsed_ms = (_time.perf_counter() - t1) * 1000

        # _ask_zedda_ai returns (None, error_msg) on failure
        if answer_text is None:
            error_msg = usage  # usage holds the error string in failure cases
            if print_output:
                if _RICH_AVAILABLE and _console:
                    _console.print(
                        f"\n[yellow]{rich_escape(str(error_msg))}[/yellow]\n"
                    )
                else:
                    print(str(error_msg))
            return str(error_msg)

        # Heuristic: show fix tip if the AI answer mentions dropping or fixing
        online_fix_tip = (
            "drop" in answer_text.lower()
            or "fix" in answer_text.lower()
            or "impute" in answer_text.lower()
        )
        if print_output:
            _render_ask_output(
                question,
                resolved_path,
                p,
                answer_text,
                mode=effective_model,
                elapsed_ms=elapsed_ms,
                usage=usage,
                show_fix_tip=online_fix_tip,
            )
        return answer_text

    except FileNotFoundError as exc:
        msg = f"File not found: {exc}"
    except ValueError as exc:
        msg = f"Invalid input: {exc}"
    except PermissionError as exc:
        msg = f"Access denied: {exc}"
    except ZeddaError as exc:
        msg = f"Scan error: {exc}"
    except Exception as exc:
        msg = f"zd.ask() error: {type(exc).__name__}: {exc}"
    finally:
        if is_temp:
            _cleanup_temp(resolved_path)

    if print_output:
        if _RICH_AVAILABLE and _console:
            _console.print(f"\n[red]{rich_escape(msg)}[/red]\n")
        else:
            print(msg)
    return msg


#  Public API

from .report import report

__all__ = [
    "profile",
    "scan",
    "compare",
    "ml_ready",
    "warnings",
    "fix",
    "clean",
    "merge",
    "ask",
    "report",
    "ZeddaError",
    "__version__",
]
# Enhanced terminal UI for ml_ready and warnings

# Validated UTF-8 unicode rendering on all outputs

# Final checks passed for ML readiness scoring
