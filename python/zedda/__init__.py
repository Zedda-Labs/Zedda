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
"""

from __future__ import annotations

import math
import ctypes
import time
import re
from pathlib import Path


# ─────────────────────────────────────────────────────────────────
#  Public error class
# ─────────────────────────────────────────────────────────────────
class ZeddaError(Exception):
    """User-friendly error raised by the Zedda engine."""
    pass


__version__ = "0.4.2"
__author__  = "zedda contributors"


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
    from rich.console import Console
    from rich.table   import Table
    from rich.text    import Text
    from rich.panel   import Panel
    from rich import box
    from rich.markup import escape as rich_escape  # SEC-GEN02
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
_ARROW_ARRAY_SIZE  = 256

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
        raise RuntimeError(
            "zedda C++ core not found.\n"
            "Please reinstall: pip install zedda"
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
def scan(path: str, sample_size: int = None, allowed_dir: str = None) -> object:
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

    # SEC-P02: Reject paths containing null bytes (C string terminator attack)
    if '\x00' in str(path):
        raise ZeddaError("Path contains null bytes - rejected for safety.")

    file_path = Path(path)
    if not file_path.exists():
        raise ZeddaError(
            f"File not found: '{path}'\n"
            "Tip: Use an absolute path or check your spelling."
        )

    # SEC-P02: Resolve symlinks and check allowed directory
    resolved = file_path.resolve()
    if allowed_dir:
        allowed = Path(allowed_dir).resolve()
        if not str(resolved).startswith(str(allowed)):
            raise ZeddaError(
                f"Path '{path}' resolves to '{resolved}' which is outside "
                f"allowed directory '{allowed_dir}'."
            )

    # SEC-DOS01: Reject 0-byte files before calling C++ core
    if resolved.stat().st_size == 0:
        raise ZeddaError(
            f"File is empty (0 bytes): '{path}'\n"
            "Tip: Check that the file was written correctly."
        )

    ext = file_path.suffix.lower()
    supported = {".csv", ".parquet", ".arrow"}
    if ext not in supported:
        raise ZeddaError(
            f"Unsupported format: '{ext}'.\n"
            f"Supported: {', '.join(sorted(supported))}"
        )

    # ── Auto-sampling logic ───────────────────────────────────────
    is_sampled = False
    if sample_size is not None:
        is_sampled = True
    elif file_path.stat().st_size > 1024 * 1024 * 1024:   # 1 GB threshold
        is_sampled  = True
        sample_size = 2_000_000

    safe_sample = sample_size if sample_size else 1_000_000

    try:
        if ext in (".parquet", ".arrow"):
            return _scan_arrow(path, is_sampled=is_sampled, sample_size=safe_sample)
        profile_obj = _core.profile(path, False, is_sampled, safe_sample)
        if is_sampled:
            total_rows = _count_lines(path)
            _SAMPLED_INFO[path] = (profile_obj.num_rows, total_rows)
        return profile_obj
    except Exception as e:  # SEC-DOS03: Catch all exceptions including ArrowInvalid
        raise ZeddaError(str(e)) from None


# ─────────────────────────────────────────────────────────────────
#  _scan_arrow() — zero-copy Parquet → C++ via Arrow C Data Interface
#
#  Phase 3 features:
#    • Stratified row-group sampling (reads only 6 representative groups)
#    • Parquet Footer Cheat Code: exact nulls/min/max from metadata
#    • Confidence intervals in terminal output when sampled
# ─────────────────────────────────────────────────────────────────
def _scan_arrow(path: str, is_sampled: bool = False, sample_size: int = 1_000_000) -> object:
    try:
        import pyarrow.parquet as pq
        import pyarrow as pa
    except ImportError:
        raise ZeddaError("pyarrow is required for Parquet. Run: pip install pyarrow")

    t0 = time.perf_counter()
    pf = pq.ParquetFile(path)

    total_rows     = pf.metadata.num_rows
    num_row_groups = pf.metadata.num_row_groups

    # ── Stratified sampling: pick 6 representative row groups ─────
    #    Covers the start, middle, and end of the dataset.
    #    This is statistically more reliable than purely random.
    if num_row_groups <= 6 or not is_sampled:
        selected_groups = list(range(num_row_groups))
        final_is_sampled = False
    else:
        mid = num_row_groups // 2
        selected_groups = sorted({
            0, 1,
            mid - 1, mid,
            num_row_groups - 2, num_row_groups - 1,
        })
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
            array_buf  = (ctypes.c_uint8 * _ARROW_ARRAY_SIZE)()

            ptr_schema = ctypes.addressof(schema_buf)
            ptr_array  = ctypes.addressof(array_buf)

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
        exact_min   = None
        exact_max   = None
        footer_ok   = True

        for rg_idx in range(num_row_groups):
            try:
                col_meta = pf.metadata.row_group(rg_idx).column(i)
                stats    = col_meta.statistics
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
            col.null_count     = exact_nulls
            col.null_pct       = (exact_nulls / total_rows * 100.0) if total_rows > 0 else 0.0
            col.non_null_count = total_rows - exact_nulls
            col.has_high_nulls = col.null_pct > 20.0

            if (exact_min is not None and exact_max is not None
                    and isinstance(exact_min, (int, float))
                    and isinstance(exact_max, (int, float))):
                col.val_min = float(exact_min)
                col.val_max = float(exact_max)
                col.range   = float(exact_max) - float(exact_min)

    profile_obj.scan_time_ms = (time.perf_counter() - t0) * 1000.0
    profile_obj.is_sampled   = final_is_sampled

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
def profile(path: str, sample_size: int = None) -> object:
    """
    Profile a file and print a beautiful terminal report.

    One line does everything::

        import zedda as zd
        zd.profile("data.csv")
        zd.profile("big_file.parquet", sample_size=500_000)

    Args:
        path:        Path to your data file (.csv, .parquet, .arrow).
        sample_size: Max rows to sample (auto if file > 500 MB).

    Returns:
        DatasetProfile (also prints report to terminal).
    """
    if _RICH_AVAILABLE and _console:
        _console.print(f"\n[bold blue]zedda[/bold blue] [dim]v{__version__}[/dim]")
        _console.print(f"[dim]Scanning[/dim] [cyan]{path}[/cyan]...\n")

    result = scan(path, sample_size=sample_size)
    _print_report(result)
    return result


# ─────────────────────────────────────────────────────────────────
#  _collect_warnings() — shared warning logic used by profile + warnings()
# ─────────────────────────────────────────────────────────────────
def _collect_warnings(p: object) -> list:
    warn_list = []
    for col in p.columns:
        # High nulls warning
        if col.null_pct > 20:
            warn_list.append(
                f"[red]![/red]  '{rich_escape(col.name)}' - "
                f"{col.null_pct:.1f}% missing. Consider dropping or imputing."
            )

        # Constant column warning
        if col.is_constant:
            warn_list.append(
                f"[yellow]![/yellow]  '{rich_escape(col.name)}' - "
                "only 1 unique value. Useless for ML, drop it."
            )

        # Possible ID column (very high cardinality on int)
        if col.type_str == "int" and col.unique_pct > 95:
            warn_list.append(
                f"[blue]i[/blue]  '{rich_escape(col.name)}' - "
                f"{col.unique_pct:.0f}% unique. Looks like an ID column."
            )

        # Binary target candidate
        if (col.unique_approx <= 3 and col.type_str == "int"
                and col.val_min == 0 and col.val_max == 1):
            warn_list.append(
                f"[green]V[/green]  '{rich_escape(col.name)}' - "
                "binary column (0/1). Good ML target candidate."
            )

        # Extreme outlier hint (if max >> mean by 10x)
        if (col.type_str in ("int", "float")
                and col.mean > 0
                and col.unique_approx > 5
                and col.val_max > 10
                and "ratio" not in col.name.lower()
                and "pct" not in col.name.lower()):
            if col.val_max > col.mean * 10:
                is_int = col.type_str == "int"
                warn_list.append(
                    f"[yellow]![/yellow]  '{rich_escape(col.name)}' - "
                    f"max ({_format_num(col.val_max, is_int)}) is "
                    f"{col.val_max/col.mean:.0f}x above mean. Outliers likely."
                )
    return warn_list


# ─────────────────────────────────────────────────────────────────
#  _quality_score() / _quality_score_display() — Data Quality Score
# ─────────────────────────────────────────────────────────────────
def _quality_score(p) -> int:
    """Compute a 0-100 data quality score from the profile object."""
    score = 100
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
        1 for c in p.columns
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


def _quality_score_display(p: object, console) -> None:
    """Print a visual quality score bar to the console."""
    score  = _quality_score(p)
    filled = score // 10
    bar    = "=" * filled + "-" * (10 - filled)

    if score >= 80:
        color, label = "green", "GOOD"
    elif score >= 60:
        color, label = "yellow", "FAIR"
    else:
        color, label = "red", "POOR"

    hints = []
    high_null = sum(1 for c in p.columns if c.has_high_nulls)
    constant  = sum(1 for c in p.columns if c.is_constant)
    outlier_c = sum(
        1 for c in p.columns
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
            abs_r  = abs(cr.r)
            color  = "red" if abs_r >= 0.9 else "yellow"
            action = ("Drop one before ML training."
                      if abs_r >= 0.95
                      else "Review before feature selection.")
            sym    = "++" if cr.direction == "positive" else "+-"
            alerts.append(
                f"  [{color}]{sym} r={cr.r:+.2f}[/{color}]  "
                f"'[cyan]{cr.col_a}[/cyan]' <-> '[cyan]{cr.col_b}[/cyan]'  "
                f"[dim]{action}[/dim]"
            )

    if alerts:
        lines = ["[bold]Pearson Correlation Alerts:[/bold]  [dim](single-pass O(1) math)[/dim]"]
        for a in alerts[:5]:
            lines.append(a)
        if len(alerts) > 5:
            lines.append(f"  [dim]... and {len(alerts)-5} more pairs.[/dim]")
        console.print("\n".join(lines) + "\n")


# ─────────────────────────────────────────────────────────────────
#  _print_report() — full Rich terminal report (used by profile())
# ─────────────────────────────────────────────────────────────────
def _print_report(p: object) -> None:
    if not _RICH_AVAILABLE or _console is None:
        _print_plain(p)
        return

    # ── Dataset summary panel ─────────────────────────────────────
    title         = "[bold blue]Dataset Overview[/bold blue]"
    sampled_lines = ""
    if p.is_sampled:
        title += "  [yellow]⚡ SAMPLED[/yellow]"
        scanned_rows, total_rows = _SAMPLED_INFO.get(p.file_path, (p.num_rows, p.num_rows))
        sample_pct  = (scanned_rows / total_rows * 100.0) if total_rows > 0 else 0.0
        is_parquet  = Path(p.file_path).suffix.lower() in (".parquet", ".arrow")
        method_str  = "nulls/min/max exact from footer" if is_parquet else "early-stop/reservoir sampling"
        sampled_lines = (
            f"\n  [yellow]⚡ SAMPLED[/yellow]  [dim]{scanned_rows:,} of {total_rows:,} rows "
            f"({sample_pct:.1f}%)[/dim]"
            f"\n            [dim]{method_str}[/dim]"
        )

    rows_display = f"{p.num_rows:,}" if p.num_rows >= 0 else "unknown"

    scan_ms = p.scan_time_ms
    scan_str = f"{scan_ms/1000:.1f} sec" if scan_ms >= 10_000 else f"{scan_ms:.0f} ms"

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
    table.add_column("Column",  style="bold cyan", min_width=12)
    table.add_column("Type",    style="magenta",   min_width=6)
    table.add_column("Nulls",   justify="right",   min_width=8)
    table.add_column("Unique~", justify="right",   min_width=8)
    table.add_column("Mean",    justify="right",   min_width=12)
    table.add_column("CI +/-95%", justify="right",   min_width=10)
    table.add_column("Min",     justify="right",   min_width=12)
    table.add_column("Max",     justify="right",   min_width=12)
    table.add_column("Flags",   min_width=14)

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
            ci_str   = "-"
            min_str  = "-"
            max_str  = "-"

        # Health flags
        flags = []
        if col.has_high_nulls:       flags.append("[red]HIGH NULL[/red]")
        if col.is_constant:          flags.append("[yellow]CONST[/yellow]")
        if col.is_high_cardinality:  flags.append("[blue]HIGH CARD[/blue]")
        flags_str = " ".join(flags) if flags else "[dim]ok[/dim]"

        # Column name truncation
        if len(col.name) > 16:
            col_display = col.name[:15] + "…"
            truncated_names.append(col.name)
        else:
            col_display = col.name

        table.add_row(
            col_display,
            col.type_str,
            null_cell,
            str(col.unique_approx),
            mean_str,
            ci_str,
            min_str,
            max_str,
            Text.from_markup(flags_str),
        )

    _console.print(table)

    if truncated_names:
        _console.print("[dim]  * Full column names: " + " | ".join(truncated_names) + "[/dim]\n")
    else:
        _console.print()

    # ── Smart Warnings ────────────────────────────────────────────
    warnings_list = _collect_warnings(p)
    if warnings_list:
        warn_lines = ["[bold]Smart Warnings:[/bold]"]
        for w in warnings_list[:5]:
            warn_lines.append(f"  {w}")
        if len(warnings_list) > 5:
            warn_lines.append(
                f"  [dim]... and {len(warnings_list)-5} more. "
                f"Call zd.warnings(\"{p.file_name}\") for full list.[/dim]"
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


def _print_plain(p: object) -> None:
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
        mean_s   = _format_num(col.mean) if col.type_str in ("int", "float") else "-"
        col_name = col.name if len(col.name) <= 12 else col.name[:10] + ".."
        print(f"{col_name:<14}{col.type_str:<8}{col.null_pct:.1f}%     {mean_s}")


# ─────────────────────────────────────────────────────────────────
#  compare() — diff two datasets for drift detection
# ─────────────────────────────────────────────────────────────────
def compare(path_a: str, path_b: str, sample_size: int = None) -> None:
    """
    Compare two datasets side by side.

    Shows schema differences, null rate changes, and distribution
    shifts (z-score drift detection) between two files.

    Args:
        path_a (str): Path to the first dataset (e.g. training data).
        path_b (str): Path to the second dataset (e.g. production data).
        sample_size (int, optional): Max rows to read per file.

    Example::

        import zedda as zd
        zd.compare("train.csv", "prod.csv")
    """
    p_a = scan(path_a, sample_size=sample_size)
    p_b = scan(path_b, sample_size=sample_size)

    if not _RICH_AVAILABLE or _console is None:
        print("Rich not available — install it: pip install rich")
        return

    _console.print()
    cols_a   = {c.name: c for c in p_a.columns}
    cols_b   = {c.name: c for c in p_b.columns}
    all_cols = list(dict.fromkeys(list(cols_a) + list(cols_b)))

    for name in all_cols:
        ca = cols_a.get(name)
        cb = cols_b.get(name)

        if ca and cb and ca.type_str in ("int", "float") and cb.type_str in ("int", "float"):
            shift_pct = abs(ca.mean - cb.mean) / ca.mean if ca.mean > 0 else 0
            shift_z   = abs(ca.mean - cb.mean) / ca.stddev if ca.stddev > 0 else 0

            if shift_z > 1.0 or shift_pct > 0.2:
                _console.print(f"[red]![/red] DRIFT DETECTED in '{rich_escape(name)}':")
                _console.print(
                    f"   Train mean: {_format_num(ca.mean, ca.type_str=='int')} -> "
                    f"Live mean: {_format_num(cb.mean, cb.type_str=='int')}  "
                    f"({shift_pct:.0%} shift!)"
                )
            else:
                _console.print(f"[green]V[/green] '{rich_escape(name)}' distribution stable")

        elif ca and cb and ca.type_str not in ("int", "float") and cb.type_str not in ("int", "float"):
            if cb.unique_approx > ca.unique_approx:
                _console.print(f"[red]![/red] NEW category in '{rich_escape(name)}' (not seen in training)")
            else:
                _console.print(f"[green]V[/green] '{rich_escape(name)}' distribution stable")
        elif not ca:
            _console.print(f"[red]![/red] NEW column '{rich_escape(name)}' in live data (not in training)")

    _console.print()


# ─────────────────────────────────────────────────────────────────
#  warnings() — show ALL warnings for a file (no truncation)
# ─────────────────────────────────────────────────────────────────
def warnings(path: str) -> None:
    """
    Show ALL warnings for a file - not truncated.

    Use after ``zd.profile()`` if you see '... and N more warnings'.

    Args:
        path (str): Path to a ``.csv``, ``.parquet``, or ``.arrow`` file.

    Example::

        import zedda as zd
        zd.warnings("data.csv")
    """
    p = scan(path)
    _console.print(f"\n[bold]All Warnings for:[/bold] {Path(path).name}\n")
    all_warnings = _collect_warnings(p)
    if not all_warnings:
        _console.print("  [green]No warnings - data looks clean![/green]\n")
        return
    _console.print("\n".join(f"  {w}" for w in all_warnings) + "\n")


# ─────────────────────────────────────────────────────────────────
#  ml_ready() — ML readiness check + actionable code suggestions
# ─────────────────────────────────────────────────────────────────
def ml_ready(path: str, sample_size: int = None) -> None:
    """
    Check if a dataset is ready for Machine Learning.

    Provides a score (0–100) and actionable pandas code snippets
    for each issue found (nulls, outliers, categoricals, correlations).

    Args:
        path (str): Path to a ``.csv``, ``.parquet``, or ``.arrow`` file.
        sample_size (int, optional): Max rows to sample.

    Example::

        import zedda as zd
        zd.ml_ready("data.csv")
    """
    p = scan(path, sample_size=sample_size)
    if not _RICH_AVAILABLE or _console is None:
        print("Rich not available — install it: pip install rich")
        return

    score = _quality_score(p)
    _console.print(f"\n[bold]ML Readiness: {score}/100[/bold]")

    next_steps = []

    for col in p.columns:
        safe    = _safe_col_name(col.name)  # SEC-P01: sanitized name
        display = rich_escape(col.name)

        # ── Missing values ─────────────────────────────────────────
        if col.null_pct > 0:
            _console.print(f"[red]X[/red] '{display}' has {col.null_pct:.0f}% nulls - impute before training")
            if col.type_str in ("int", "float"):
                next_steps.append(f"df[{safe}] = df[{safe}].fillna(df[{safe}].median())")
            else:
                next_steps.append(f"df[{safe}] = df[{safe}].fillna(df[{safe}].mode()[0])")

        # ── Outliers ──────────────────────────────────────────────
        if (col.type_str in ("int", "float")
                and col.val_max > 10
                and col.mean > 0
                and col.val_max > col.mean * 10
                and "ratio" not in col.name.lower()
                and "pct" not in col.name.lower()):
            _console.print(
                f"[red]X[/red] '{display}' has extreme outliers "
                f"(max = {_format_num(col.val_max/col.mean)}x mean)"
            )
            # SEC-P01: Use sanitized name in generated code
            next_steps.append(
                f"df[{safe}] = df[{safe}].clip(upper=df[{safe}].quantile(0.99))"
            )

        # ── High-cardinality categoricals ─────────────────────────
        if col.type_str not in ("int", "float") and col.unique_approx > 100:
            _console.print(f"[yellow]![/yellow]  '{display}' has {col.unique_approx}+ unique values - encode carefully")

        # ── Binary target candidate ───────────────────────────────
        if (col.type_str in ("int", "float")
                and col.val_min == 0
                and col.val_max == 1
                and col.unique_approx <= 2):
            _console.print(f"[green]V[/green] '{display}' is binary - good ML target")

        # ── Categorical encoding suggestions ──────────────────────
        if (col.type_str not in ("int", "float")
                and 1 < col.unique_approx <= 100
                and col.null_pct == 0
                and len(next_steps) < 5):
            next_steps.append(f"df = pd.get_dummies(df, columns=[{safe}], drop_first=True)")

    # ── Correlation checks ────────────────────────────────────────
    for cr in p.correlations:
        if abs(cr.r) >= 0.95:
            safe_a = _safe_col_name(cr.col_a)
            _console.print(
                f"🔗 '{rich_escape(cr.col_a)}' <-> '{rich_escape(cr.col_b)}' "
                f"corr={cr.r:.2f} - drop one"
            )
            next_steps.append(f"df = df.drop(columns=[{safe_a}])")
            break  # Show one to avoid flooding

    # ── Suggested next steps ──────────────────────────────────────
    if next_steps:
        # De-duplicate while preserving order
        next_steps = list(dict.fromkeys(next_steps))
        _console.print("\n[dim]Suggested next steps:[/dim]")
        for step in next_steps[:3]:
            _console.print(f"  [cyan]{step}[/cyan]")
    _console.print()


# ─────────────────────────────────────────────────────────────────
#  fix() — Automated Pandas Fix Code Generator
#
#  Scans the dataset and generates copy-paste-ready pandas code to
#  fix the most common data quality problems:
#    - Missing values (nulls)       → fillna with median or mode
#    - Extreme outliers             → log-transform (np.log1p)
#    - Disguised ID columns         → drop (useless for ML)
#    - High-cardinality strings     → label encode (pd.Categorical)
#
#  New in v0.4.1:
#    - apply=True returns an actual cleaned DataFrame (not just code)
#    - All generated code uses repr() for column names (SEC-P01)
# ─────────────────────────────────────────────────────────────────
def fix(path: str, apply: bool = False) -> object:
    """
    Scan a dataset and generate copy-paste-ready pandas fix code.

    Automatically detects the most common data quality problems and
    prints grouped, actionable pandas snippets you can paste directly
    into your data preparation notebook or script.

    Issues detected and fixed:

    * **Missing values** — numeric columns get ``fillna(median())``;
      string columns get ``fillna(mode()[0])``.
    * **Extreme outliers** — columns where max > 10x mean get a
      ``np.log1p()`` transform suggestion.
    * **ID columns** — integer columns with >95% unique values are
      flagged as likely row IDs and suggested for dropping.
    * **High-cardinality strings** — string columns with >50 unique
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
    if not _RICH_AVAILABLE or _console is None:
        print("Rich not available. Install it: pip install rich")
        return None

    # ── Run the C++ engine silently ───────────────────────────────
    p = scan(path)

    # ── Collect fixes grouped by category ────────────────────────
    # Each entry: (display_line, code_line)
    # display_line = what we show in the grouped section
    # code_line    = what goes in the final copy-paste block
    null_fixes     = []  # Missing value imputation fixes
    outlier_fixes  = []  # Extreme outlier transform fixes
    id_col_fixes   = []  # Useless ID column drop fixes
    encoding_fixes = []  # High-cardinality string encoding fixes

    for col in p.columns:
        # SEC-P01: Use repr() for column names in all generated code.
        # This escapes quotes, backslashes, and control characters,
        # preventing code injection via malicious CSV column names.
        safe         = _safe_col_name(col.name)
        display_name = rich_escape(col.name)  # Safe for Rich markup

        # ── Missing values ────────────────────────────────────────
        # Threshold: flag columns with more than 1% nulls
        if col.null_pct > 1:
            if col.type_str in ("int", "float"):
                # Median is robust to outliers — better than mean
                null_fixes.append((
                    f"  [cyan]{display_name}[/cyan]  "
                    f"[dim]→ {col.null_pct:.1f}% nulls → fillna(median)[/dim]",
                    f"df[{safe}] = df[{safe}].fillna(df[{safe}].median())  "
                    f"# {col.null_pct:.1f}% nulls"
                ))
            elif col.type_str in ("str", "unknown"):
                # Mode (most frequent value) is the standard for categoricals
                null_fixes.append((
                    f"  [cyan]{display_name}[/cyan]  "
                    f"[dim]→ {col.null_pct:.1f}% nulls → fillna(mode)[/dim]",
                    f"df[{safe}] = df[{safe}].fillna(df[{safe}].mode()[0])  "
                    f"# {col.null_pct:.1f}% nulls"
                ))

        # ── Extreme outliers ──────────────────────────────────────
        # Flag numeric columns where max > 10x the mean.
        # Skip ratio/percent columns — extreme max is expected there.
        if (col.type_str in ("int", "float")
                and col.mean > 0
                and col.val_max > col.mean * 10
                and col.unique_approx > 5
                and "ratio" not in col.name.lower()
                and "pct"   not in col.name.lower()):
            ratio = col.val_max / col.mean
            outlier_fixes.append((
                f"  [cyan]{display_name}[/cyan]  "
                f"[dim]→ max is {ratio:.0f}x mean → log1p transform[/dim]",
                f"df[{safe}_log] = np.log1p(df[{safe}])  "
                f"# max={col.val_max:,.0f} is {ratio:.0f}x mean"
            ))

        # ── Disguised ID columns ──────────────────────────────────
        # An integer column that is almost entirely unique is almost
        # certainly a row identifier — useless for ML models.
        if col.type_str == "int" and col.unique_pct > 95:
            id_col_fixes.append((
                f"  [cyan]{display_name}[/cyan]  "
                f"[dim]→ {col.unique_pct:.0f}% unique → likely ID column → drop[/dim]",
                f"df = df.drop(columns=[{safe}])  "
                f"# {col.unique_pct:.0f}% unique values — ID column"
            ))

        # ── High-cardinality string encoding ──────────────────────
        # String columns with >50 distinct values need special encoding
        # before feeding into most ML models (which require numbers).
        if col.type_str in ("str", "unknown") and col.unique_approx > 50:
            encoding_fixes.append((
                f"  [cyan]{display_name}[/cyan]  "
                f"[dim]→ {col.unique_approx} unique values → label encode[/dim]",
                f"df[{safe}] = pd.Categorical(df[{safe}]).codes  "
                f"# {col.unique_approx} unique values"
            ))

    # ── Check if there is anything to fix ────────────────────────
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

    # ── Print summary header ──────────────────────────────────────
    n_issues = len(all_fixes)
    summary = (
        f"[bold]{n_issues} issue{'s' if n_issues > 1 else ''} found[/bold] "
        f"across [cyan]{p.num_cols}[/cyan] columns.\n"
        f"[dim]Scroll down for the full copy-paste block.[/dim]"
    )
    _console.print(Panel(
        summary,
        title=f"[bold yellow]zd.fix() - {Path(path).name}[/bold yellow]",
        border_style="yellow",
        expand=False,
    ))

    # ── Print each category with a section header ─────────────────
    if null_fixes:
        _console.print(
            "\n[bold red]⬤  MISSING VALUES[/bold red]  "
            "[dim](fills nulls with median / mode)[/dim]"
        )
        for display, _ in null_fixes:
            _console.print(display)

    if outlier_fixes:
        _console.print(
            "\n[bold magenta]⬤  OUTLIERS[/bold magenta]  "
            "[dim](log1p shrinks extreme right-skewed values)[/dim]"
        )
        for display, _ in outlier_fixes:
            _console.print(display)

    if id_col_fixes:
        _console.print(
            "\n[bold blue]⬤  ID COLUMNS[/bold blue]  "
            "[dim](high-uniqueness integers — useless for ML)[/dim]"
        )
        for display, _ in id_col_fixes:
            _console.print(display)

    if encoding_fixes:
        _console.print(
            "\n[bold cyan]⬤  ENCODING[/bold cyan]  "
            "[dim](high-cardinality strings → numeric codes)[/dim]"
        )
        for display, _ in encoding_fixes:
            _console.print(display)

    # ── Print the final copy-paste block ─────────────────────────
    _console.print(
        "\n[bold]Copy-Paste Block:[/bold]  "
        "[dim](paste this into your notebook or script)[/dim]"
    )

    # Print imports only if they are actually needed by the generated code
    needs_numpy  = bool(outlier_fixes)   # np.log1p
    needs_pandas = bool(encoding_fixes)  # pd.Categorical
    if needs_numpy:
        _console.print("[dim]import numpy as np[/dim]")
    if needs_pandas:
        _console.print("[dim]import pandas as pd[/dim]")

    for _, code in all_fixes:
        _console.print(f"  [cyan]{code}[/cyan]")
    _console.print()

    # ── apply=True: actually execute the fixes and return a DataFrame ─
    if apply:
        try:
            import pandas as pd
            import numpy as np
        except ImportError:
            _console.print(
                "[red]pandas / numpy not installed — cannot apply fixes.[/red]\n"
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
            if (col.type_str in ("int", "float")
                    and col.mean > 0
                    and col.val_max > col.mean * 10
                    and col.unique_approx > 5
                    and "ratio" not in col.name.lower()
                    and "pct"   not in col.name.lower()):
                df[col.name + "_log"] = np.log1p(df[col.name])

        # Apply ID column drops
        id_cols = [
            col.name for col in p.columns
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
                f"[green]✔ Applied {n_issues} fix{'es' if n_issues > 1 else ''}.[/green]  "
                f"DataFrame shape: [cyan]{df.shape}[/cyan]",
                title="[bold green]zd.fix(apply=True) — Done[/bold green]",
                border_style="green",
                expand=False,
            )
        )
        return df

    return None


# ─────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────
__all__ = [
    "profile",
    "scan",
    "compare",
    "ml_ready",
    "warnings",
    "fix",
    "ZeddaError",
    "__version__",
]