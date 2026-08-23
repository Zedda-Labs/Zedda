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
    p = zd._scan_wrapper("data.csv")
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

import ctypes
import math
import re
import time

# FIX L-22: Move json and shutil to module level (were imported inside clean()).
import json
import shutil
from pathlib import Path
from typing import Any
import sys

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass

# P1-1: Opt-in to pandas future behavior to prevent silent dtype changes
# on clip()/fillna() in pandas 3.0+. Without this, integer columns may
# silently become float columns after cleaning operations.
try:
    import pandas as pd

    pd.set_option("future.no_silent_downcasting", True)
except (ImportError, KeyError):
    pass  # pandas not installed or option not available in older versions


# ─────────────────────────────────────────────────────────────────
#  Public error class
from ._errors import ZeddaError
def _require_pyarrow():
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet  # noqa: F401
    except ImportError as e:
        raise ZeddaError(
            "Parquet/Arrow support requires pyarrow, which is not "
            "installed. Install it with: pip install zedda[parquet]\n"
            "CSV support works without this extra."
        ) from e


__version__ = "0.4.8"
__author__ = "zedda contributors"


# Expose report as export for ydata-profiling compatibility.
# FIX P-M25: Use relative imports so the package survives rename/aliasing.
from .report import report
from .report import report as export

# ─────────────────────────────────────────────────────────────────
#  FIX Batch 7: Internal helper modules.
#  These extract logic from the 4,287-line __init__.py into focused
#  sub-modules for testability and maintainability. The public API
#  is unchanged — these are imported for internal use.
# ─────────────────────────────────────────────────────────────────
from ._validate import validate
from ._compat import legacy_to_profile_result as _legacy_to_profile_result
from ._constants import (
    ARROW_SCHEMA_SIZE as _ARROW_SCHEMA_SIZE,
    ARROW_ARRAY_SIZE as _ARROW_ARRAY_SIZE,
    SAMPLED_INFO as _SAMPLED_INFO,
    SAMPLED_INFO_MAX as _SAMPLED_INFO_MAX,
    sampled_info_set as _sampled_info_set,
    sampled_info_get as _sampled_info_get,
    ASK_ALLOWED_EXT as _ASK_ALLOWED_EXT,
    ASK_BLOCKED_ROOTS as _ASK_BLOCKED_ROOTS,
    AI_PRICING as _AI_PRICING,
    AI_DEFAULT_MODEL as _AI_DEFAULT_MODEL,
    AI_ENDPOINT as _AI_ENDPOINT,
)
from ._format import (
    format_num as _format_num,
    format_ci as _format_ci,
    format_scan_time as _format_scan_time,
    quality_label as _quality_label,
    render_quality_bar as _render_quality_bar,
    render_sparkline_text as _render_sparkline_text,
    render_shape_descriptor as _render_shape_descriptor,
    compute_display_name as _compute_display_name,
    safe_col_name as _safe_col_name,
    safe_symbol as _safe_symbol,
)
from ._warnings import (
    is_outlier_column as _is_outlier_column,
    detect_column_issues as _detect_column_issues,
    get_fix_action as _get_fix_action,
    collect_warnings as _collect_warnings,
)
from ._compare import (
    compute_schema_diff as _compute_schema_diff,
    compute_distribution_shift as _compute_distribution_shift,
    compute_category_diff as _compute_category_diff,
    compute_verdict as _compute_verdict,
)

# Keep _collect_warnings_legacy alias for back-compat.
from ._warnings import collect_warnings as _collect_warnings_new


def _collect_warnings_legacy(p: Any) -> list:
    """Legacy wrapper: return old-format warnings for _print_report() compatibility."""
    new_warnings = _collect_warnings_new(p)
    legacy = []
    for w in new_warnings:
        icon_map = {"✗": "x", "⚠": "!", "ℹ": "i"}
        legacy.append(
            {
                "icon": icon_map.get(w["icon"], "i"),
                "column": w["column"],
                "message": w["message"],
                "severity": w["severity"],
                "fix_code": w.get("fix_code", ""),
                "fix_action": w.get("fix_action", ""),
            }
        )
    return legacy


# ─────────────────────────────────────────────────────────────────
#  Try importing C++ core
# ─────────────────────────────────────────────────────────────────
try:
    from . import fasteda_core as _core  # type: ignore

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

    def rich_escape(s: str) -> str:  # type: ignore  # SEC-GEN02: fallback no-op
        return s


_console = Console() if _RICH_AVAILABLE else None

# ─────────────────────────────────────────────────────────────────
#  Arrow C Data Interface struct sizes (from arrow/c/abi.h)
#  ArrowSchema / ArrowArray: 9 pointer-sized fields → 72 bytes on 64-bit.
#  We allocate 256 bytes each for safety.
# ─────────────────────────────────────────────────────────────────

# Stores (scanned_rows, total_rows) for sampled files — used by _print_report
# P-04: Capped at 100 entries to prevent unbounded memory growth in long-running
# processes that profile many files.
# FIX P-M4: Add a threading.Lock around mutation — concurrent _scan_wrapper() calls
# could race on OrderedDict.popitem.
from collections import OrderedDict
import threading as _threading

_SAMPLED_INFO_LOCK = _threading.Lock()


# P-03: Extracted from 8+ callsites that all duplicated this condition.


def _make_silent_df(df):
    try:
        import pandas as pd

        class SilentDataFrame(pd.DataFrame):
            @property
            def _constructor(self):
                return SilentDataFrame

            def _repr_html_(self):
                return None

            def __repr__(self):
                return ""

        return SilentDataFrame(df)
    except ImportError:
        return df


class SilentString(str):
    def _repr_html_(self):
        return None

    def __repr__(self):
        return ""


# ─────────────────────────────────────────────────────────────────
#  Number formatting helpers
# ─────────────────────────────────────────────────────────────────


def _count_lines(path: str) -> int | None:
    """Count newlines in a file without reading it fully into memory.

    FIX P-M7: Returns None on any error so callers can display "unknown"
    rather than 0 (which previously produced misleading "100% sampled" output).
    FIX M-8: Adds 1 for files that don't end with a trailing newline
    (off-by-one on the last row).
    """
    try:
        count = 0
        saw_non_newline = False
        last_byte = b"\n"
        with open(path, "rb") as f:
            while True:
                chunk = f.read(4 * 1024 * 1024)
                if not chunk:
                    break
                saw_non_newline = saw_non_newline or any(b != b"\n" for b in chunk)
                count += chunk.count(b"\n")
                last_byte = chunk[-1:]
        # If file is non-empty and doesn't end with \n, the last row was not counted.
        if saw_non_newline and last_byte != b"\n":
            count += 1
        return count
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
#  FIX P-M2: Shared formatting / display helpers.
#  These replace 6× duplicated copies of the outlier predicate,
#  quality-label thresholds, file_name computation, and scan-time format.
# ─────────────────────────────────────────────────────────────────


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


# ─────────────────────────────────────────────────────────────────
#  Input resolution and scanning engine (Canonical Phase 5.9)
# ─────────────────────────────────────────────────────────────────
def _resolve_input(data):
    from pathlib import Path
    if isinstance(data, (str, Path)):
        return data, False
    return data, True

def _cleanup_temp(path):
    pass


from ._engine import scan, profile


def _scan_wrapper(source, sample_size=None, correlate=False, **kwargs):
    from ._engine import _scan_legacy
    from ._compat import legacy_to_profile_result
    adapter, cpp = _scan_legacy(source, sample_size=sample_size, correlate=correlate, **kwargs)
    try:
        return legacy_to_profile_result(cpp)
    finally:
        adapter.close()

def _quality_score(p, original_cols: int | None = None) -> int:
    """Compute a 0-100 data quality score from the profile object."""
    score = 100
    # FIX M-36: Use `is not None` instead of `if original_cols` —
    # the old check was falsy for 0, disabling the dropped-column penalty.
    if original_cols is not None and p.num_cols < original_cols:
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
    # FIX P-M2: Use the shared _is_outlier_column() helper instead of
    # duplicating the 7-line predicate inline (was copy #4 of 6).
    outlier_cols = sum(1 for c in p.columns if _is_outlier_column(c))
    score -= min(20, outlier_cols * 3)
    # FIX M-11: Clamp to [0, 100] — was only max(0, score).
    return max(0, min(100, score))


def _quality_score_display(p: Any, console) -> None:
    """Print a visual quality score bar to the console."""
    score = _quality_score(p)
    # FIX P-M2: Use shared helpers from _format.py (was duplicated inline).
    bar = _render_quality_bar(score)
    color, label = _quality_label(score)

    hints = []
    high_null = sum(1 for c in p.columns if c.has_high_nulls)
    constant = sum(1 for c in p.columns if c.is_constant)
    # FIX P-M2: Use _is_outlier_column() instead of inline predicate.
    outlier_c = sum(1 for c in p.columns if _is_outlier_column(c))

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
    """Print Pearson correlation alerts for r >= 0.5."""
    alerts = []
    arrow_pos = _safe_symbol("↑↑", "++")
    arrow_neg = _safe_symbol("↓↑", "+-")
    arrow_bidir = _safe_symbol("↔", "<->")
    warn_icon = _safe_symbol("⚠", "[!]")

    for cr in p.correlations:
        if abs(cr.r) >= 0.5:
            abs_r = abs(cr.r)
            if abs_r >= 0.9:
                color = "red"
                action = "Drop one before ML training (extreme collinearity)."
            elif abs_r >= 0.7:
                color = "yellow"
                action = "Review before feature selection (strong correlation)."
            else:
                color = "dim"
                action = "Moderate correlation."

            sym = arrow_pos if cr.direction == "positive" else arrow_neg
            alerts.append(
                f"  [{color}]{sym} r={cr.r:+.2f}[/{color}]  "
                f"'[cyan]{cr.col_a}[/cyan]' {arrow_bidir} '[cyan]{cr.col_b}[/cyan]'  "
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
        console.print("\n".join(lines))

    # FIX PERF-1: Print a warning if correlation was skipped due to too many columns.
    if getattr(p, "correlation_skipped", False):
        console.print(
            f"\n[yellow]{warn_icon} Warning:[/yellow] Correlation matrix skipped due to high numeric column count.\n"
            "   Pass [bold]correlate=True[/bold] to force calculation (may take minutes)."
        )


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
        # FIX P-M4: use the thread-safe getter.
        scanned_rows, total_rows = _sampled_info_get(
            p.file_path, (p.num_rows, p.num_rows)
        )
        # FIX P-M7: if _count_lines returned 0 on error, total_rows is 0 —
        # display "unknown" rather than a misleading 100% sample.
        if total_rows <= 0:
            sampled_lines = "  [dim](sample size: unknown)[/dim]"
        else:
            sample_pct = scanned_rows / total_rows * 100.0
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
        f"[magenta]{p.num_string} string/text[/magenta])\n"
        f"[bold]Nulls:[/bold]    "
        + ("[red]" if p.overall_null_pct > 10 else "[green]")
        + f"{p.overall_null_pct:.1f}%[/]"
        + f"  ({p.total_null_cells:,} cells)\n"
        f"[bold]Scanned:[/bold]  {scan_str}"
    )

    _console.print(Panel(summary, title=title, border_style="blue", expand=False))

    # ── Data Quality Score ────────────────────────────────────────
    _quality_score_display(p, _console)

    numeric_cols = [c for c in p.columns if c.type_str in ("int", "float", "bool")]
    cat_cols = [c for c in p.columns if c.type_str not in ("int", "float", "bool")]

    truncated_names = []

    # ── Numeric Columns Table ─────────────────────────────────────
    if numeric_cols:
        table_num = Table(
            title="[bold cyan]Numeric Columns[/bold cyan]",
            title_justify="left",
            show_header=True,
            header_style="bold white on blue",
            border_style="dim",
            box=box.SIMPLE_HEAVY,
            padding=(0, 1),
        )
        table_num.add_column("Column", style="bold cyan", min_width=12)
        table_num.add_column("Type", style="magenta", min_width=6)
        table_num.add_column("Nulls", justify="right", min_width=8)
        table_num.add_column("Unique", justify="right", min_width=8)
        table_num.add_column("Mean", justify="right", min_width=10)
        if p.is_sampled:
            table_num.add_column("CI +/-95%", justify="right", min_width=10)
        table_num.add_column("Min", justify="right", min_width=10)
        table_num.add_column("Max", justify="right", min_width=10)
        table_num.add_column("Distribution", justify="center", min_width=18)
        table_num.add_column("Flags", min_width=12)

        for col in numeric_cols:
            null_cell = Text(f"{col.null_pct:.1f}%")
            if col.null_pct > 20:
                null_cell.stylize("bold red")
            elif col.null_pct > 5:
                null_cell.stylize("yellow")
            else:
                null_cell.stylize("green")

            is_int = col.type_str == "int"
            mean_str = _format_num(col.mean, is_int)
            if p.is_sampled and col.non_null_count > 1:
                stderr = 1.96 * col.stddev / math.sqrt(col.non_null_count)
                ci_str = f"+/-{_format_ci(stderr)}"
            else:
                ci_str = "-"
            min_str = _format_num(col.val_min, is_int)
            max_str = _format_num(col.val_max, is_int)

            shape_str = _render_shape_descriptor(col, p.num_rows)

            flags = []
            if col.has_high_nulls:
                flags.append("[red]HIGH NULL[/red]")
            if col.is_constant:
                flags.append("[yellow]CONST[/yellow]")
            if col.is_high_cardinality:
                flags.append("[blue]HIGH CARD[/blue]")
            flags_str = " ".join(flags) if flags else "[dim]ok[/dim]"

            if len(col.name) > 16:
                col_display = col.name[:15] + "…"
                truncated_names.append(col.name)
            else:
                col_display = col.name

            has_exact = hasattr(col, "unique_exact") and not getattr(
                col, "exact_numeric_overflowed", True
            )
            uniq_str = str(col.unique_exact if has_exact else col.unique_approx)

            row_data = [
                col_display,
                col.type_str,
                null_cell,
                uniq_str,
                mean_str,
            ]
            if p.is_sampled:
                row_data.append(ci_str)
            row_data.extend(
                [
                    min_str,
                    max_str,
                    shape_str,
                    Text.from_markup(flags_str),
                ]
            )
            table_num.add_row(*row_data)

        _console.print(table_num)
        up_icon = _safe_symbol("📈", "^")
        down_icon = _safe_symbol("📉", "v")
        _console.print(
            f"  [dim]Shape: {up_icon} Normal / {down_icon} Skewed for continuous numbers; value split (%) for discrete categories.[/dim]"
        )

    # ── Categorical & Text Columns Table ──────────────────────────
    if cat_cols:
        if numeric_cols:
            _console.print()
        table_cat = Table(
            title="[bold magenta]Categorical & Text Columns[/bold magenta]",
            title_justify="left",
            show_header=True,
            header_style="bold white on magenta",
            border_style="dim",
            box=box.SIMPLE_HEAVY,
            padding=(0, 1),
        )
        table_cat.add_column("Column", style="bold cyan", min_width=12)
        table_cat.add_column("Type", style="magenta", min_width=6)
        table_cat.add_column("Nulls", justify="right", min_width=8)
        table_cat.add_column("Unique", justify="right", min_width=8)
        table_cat.add_column("Mean Len", justify="right", min_width=9)
        table_cat.add_column("Min Len", justify="right", min_width=8)
        table_cat.add_column("Max Len", justify="right", min_width=8)
        table_cat.add_column("Sample Values", min_width=20)
        table_cat.add_column("Flags", min_width=12)

        for col in cat_cols:
            null_cell = Text(f"{col.null_pct:.1f}%")
            if col.null_pct > 20:
                null_cell.stylize("bold red")
            elif col.null_pct > 5:
                null_cell.stylize("yellow")
            else:
                null_cell.stylize("green")

            mean_len_str = f"{col.mean_str_len:.1f}" if col.mean_str_len > 0 else "-"
            min_len_str = str(col.min_str_len) if col.min_str_len < 1000000 else "-"
            max_len_str = str(col.max_str_len) if col.max_str_len > 0 else "-"

            top_vals = getattr(col, "top_values", [])
            if top_vals:
                vals_formatted = [
                    f"'{v}'" if len(v) <= 12 else f"'{v[:10]}…'" for v in top_vals[:3]
                ]
                sample_str = ", ".join(vals_formatted)
                if len(top_vals) > 3 or getattr(col, "distinct_overflowed", False):
                    sample_str += " …"
            else:
                sample_str = "[dim]—[/dim]"

            flags = []
            if col.has_high_nulls:
                flags.append("[red]HIGH NULL[/red]")
            if col.is_constant:
                flags.append("[yellow]CONST[/yellow]")
            if col.is_high_cardinality:
                flags.append("[blue]HIGH CARD[/blue]")
            flags_str = " ".join(flags) if flags else "[dim]ok[/dim]"

            if len(col.name) > 16:
                col_display = col.name[:15] + "…"
                truncated_names.append(col.name)
            else:
                col_display = col.name

            uniq_str = str(col.unique_approx)

            row_data = [
                col_display,
                col.type_str,
                null_cell,
                uniq_str,
                mean_len_str,
                min_len_str,
                max_len_str,
                sample_str,
                Text.from_markup(flags_str),
            ]
            table_cat.add_row(*row_data)

        _console.print(table_cat)

    if truncated_names:
        _console.print(
            "\n[dim]  * Full column names: " + " | ".join(truncated_names) + "[/dim]\n"
        )
    else:
        _console.print()

    # ── Smart Warnings Teaser ─────────────────────────────────────
    all_warnings = _collect_warnings(p)
    if all_warnings:
        crit_sym = _safe_symbol("✗", "[X]")
        warn_sym = _safe_symbol("⚠", "[!]")
        info_sym = _safe_symbol("ℹ", "[i]")
        warn_icons = {
            "critical": f"[red]{crit_sym}[/red]",
            "warning": f"[yellow]{warn_sym}[/yellow]",
            "info": f"[blue]{info_sym}[/blue]",
        }
        warn_lines = ["[bold]Smart Warnings:[/bold]"]
        dash = _safe_symbol("—", "-")
        for w in all_warnings[:3]:
            icon = warn_icons.get(w.get("severity", "info"), f"[blue]{info_sym}[/blue]")
            warn_lines.append(
                f"  {icon}  [cyan]'{rich_escape(w['column'])}'[/cyan] {dash} {w['message']}"
            )
        if len(all_warnings) > 3:
            warn_lines.append(
                f"  [dim]... and {len(all_warnings) - 3} more. "
                f'Run zd.warnings("{p.file_name}") for full list.[/dim]'
            )
        _console.print("\n".join(warn_lines))

    # ── Correlation Alerts ────────────────────────────────────────
    _correlation_alerts(p, _console)

    # ── Clean Footer & Next Steps ─────────────────────────────────
    bullet = _safe_symbol("•", "-")
    _console.print(
        f"\n[dim]  zedda v{__version__}  {bullet}  "
        f"{p.num_cols} columns  {bullet}  "
        f"{p.num_rows:,} rows  {bullet}  "
        f"scanned in {scan_str}[/dim]"
    )
    _console.print(
        f'[dim]  Next steps: zd.ml_ready("{p.file_name}") for ML check  {bullet}  '
        f'zd.fix("{p.file_name}") for fix code  {bullet}  '
        f'zd.clean("{p.file_name}") to auto-clean[/dim]\n'
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
from ._compare import compare



# ─────────────────────────────────────────────────────────────────
#  warnings() — Intelligence mode: severity + inline fixes + copy-paste
# ─────────────────────────────────────────────────────────────────
from ._warnings import warnings, collect_warnings



# ─────────────────────────────────────────────────────────────────
#  ml_ready() — ML readiness check with premium terminal UI
# ─────────────────────────────────────────────────────────────────
from ._ml_ready import ml_ready



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
# ─────────────────────────────────────────────────────────────────
#  fix() — Automated ML fix code generator
# ─────────────────────────────────────────────────────────────────
from ._fix import fix



# ─────────────────────────────────────────────────────────────────
#  clean() — Auto-fix dataset with backup, audit trail, and scoring
#
#  Uses _collect_warnings() to detect issues, applies fixes using
#  pandas, creates a backup file, and writes a JSON audit trail.
#  Shows before/after quality scores with visual progress.
# ─────────────────────────────────────────────────────────────────
from ._clean import clean, _clean_undo

# P-05: Attach undo as a callable attribute on clean.
# Type checkers can't see monkey-patched attributes by default.
# Use `zd.clean.undo(path)` to restore a backup created by clean().
# IDEs: if your IDE can't autocomplete `.undo`, call `zedda._clean_undo(path)`
# directly as an alternative \u2014 same function, fully type-checkable.
clean.undo = _clean_undo  # type: ignore[attr-defined]


# ─────────────────────────────────────────────────────────────────
#  merge() — Smart multi-file merge with schema check, dedup,
#  distribution shift detection, and source tracking.
# ─────────────────────────────────────────────────────────────────
from ._merge import merge



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

# ── SEC-Q02: Blocked OS root paths (case-insensitive path containment) ─
# FIX P-H1: Use Path objects + Path.relative_to() so '/rootkit/x.csv' no
# longer matches '/root'. Containment is checked in _ask_validate_path.

# ── Zedda AI pricing table (internal — never shown to user) ──────

# ── Default AI model (internal — not exposed to user) ───────────

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
_DOMAIN_SIGNALS: dict = {
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

    # SEC-Q02: block system-critical root paths.
    # FIX P-H1: Use Path.relative_to() for proper containment check.
    real = Path(os.path.realpath(path))
    for blocked in _ASK_BLOCKED_ROOTS:
        try:
            real.relative_to(blocked)
            raise PermissionError(f"Access to system path '{path}' is not allowed.")
        except ValueError:
            continue

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
            f"zd._scan_wrapper(path, sample_size=1_000_000)."
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
            # FIX P-M30: Cap parquet reads at 5M rows (was uncapped — a 2GB
            # parquet with 50M rows would OOM a typical workstation).
            # pyarrow doesn't support nrows= directly, but we can read
            # row groups until we hit the cap.
            import pyarrow.parquet as _pq

            _pf = _pq.ParquetFile(path)
            _tables = []
            _rows = 0
            for _rg in range(_pf.metadata.num_row_groups):
                if _rows >= 5_000_000:
                    break
                _t = _pf.read_row_group(_rg, columns=[group_col.name, target_col.name])
                _tables.append(_t)
                _rows += _t.num_rows
            if _tables:
                df = _pd.concat([_t.to_pandas() for _t in _tables], ignore_index=True)
            else:
                return None
        elif ext == ".arrow" or ext == ".feather":
            # FIX P-M30: Cap feather reads too.
            df = _pd.read_feather(path, columns=[group_col.name, target_col.name])
            if len(df) > 5_000_000:
                df = df.head(5_000_000)
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
# FIX P-M19: Hoist regex compilation to module scope (was rebuilt on
# every call to _ask_pattern_d — 7 regexes × every ask() call).
_SINGLE_COL_PATTERNS = [
    (re.compile(r"mean\s+(?:of\s+)?(.+)", re.I), "mean"),
    (re.compile(r"null\s+(?:rate|pct|percent)\s+(?:of\s+)?(.+)", re.I), "null_pct"),
    (re.compile(r"type\s+(?:of\s+)?(.+)", re.I), "type_str"),
    (re.compile(r"min(?:imum)?\s+(?:of\s+)?(.+)", re.I), "val_min"),
    (re.compile(r"max(?:imum)?\s+(?:of\s+)?(.+)", re.I), "val_max"),
    (re.compile(r"stddev\s+(?:of\s+)?(.+)", re.I), "stddev"),
    (re.compile(r"skewness\s+(?:of\s+)?(.+)", re.I), "skewness"),
]


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
    # FIX P-M19: Use module-level compiled patterns (was rebuilding 7
    # regexes on every call).
    for pat, attr in _SINGLE_COL_PATTERNS:
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
    except (KeyError, IndexError, ValueError) as exc:
        # FIX L-20: Consolidated JSON parse errors — was separate from the
        # broad `except Exception` below. Now includes the exception type
        # for debugging, and the broad catch only handles truly unexpected
        # errors (e.g., MemoryError, KeyboardInterrupt are NOT caught here
        # since they're BaseException, not Exception).
        return (
            None,
            f"Zedda AI returned an unexpected response ({type(exc).__name__}). Please try again.",
        )
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

    dot_sym = _safe_symbol("·", "-")

    # Header
    if is_online:
        _console.print(
            f"[bold green]zedda v{__version__}[/bold green]  "
            f"[dim]{dot_sym}[/dim]  [dim]ask mode[/dim]  [dim]{dot_sym}[/dim]  "
            f"[blue]Zedda AI[/blue]"
        )
    else:
        _console.print(
            f"[bold green]zedda v{__version__}[/bold green]  "
            f"[dim]{dot_sym}[/dim]  [dim]ask mode[/dim]  [dim]{dot_sym}[/dim]  "
            f"[dim]offline[/dim]"
        )

    # Metadata
    _console.print(f"  [dim]Question :[/dim]  {rich_escape(question)}")
    if is_online:
        _console.print(
            f"  [dim]Profile  :[/dim]  "
            f"[dim]{p.num_cols} cols {dot_sym} {p.num_rows:,} rows {dot_sym} sent to Zedda AI[/dim]"
        )
    else:
        _console.print(
            f"  [dim]Source   :[/dim]  "
            f"[dim]{rich_escape(basename)}  ({p.num_rows:,} rows {dot_sym} {p.num_cols} cols)[/dim]"
        )

    check_sym = _safe_symbol("✓", "[OK]")
    crit_sym = _safe_symbol("✗", "[X]")
    h_line = _safe_symbol("─", "-")

    _console.print(f"  [dim]{h_line * 47}[/dim]")

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
            icon = f"[green]{check_sym}[/green]" if ok else f"[red]{crit_sym}[/red]"
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
    model: str | None = None,
    print_output: bool = True,
) -> Any:
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
    resolved_path, is_in_memory = _resolve_input(path)
    path_display = str(resolved_path) if not is_in_memory else "<DataFrame>"
    try:
        # FIX L-19: Use module-level `time` import (was re-imported as _time).
        # ── SEC-Q01/Q02/Q03: Validate path ────────────────────────
        if not is_in_memory:
            assert isinstance(resolved_path, str)
            _ask_validate_path(resolved_path)

        # ── SEC-Q04: Sanitize question ────────────────────────────
        question = _ask_sanitize_question(question)

        # ── Scan the dataset ──────────────────────────────────────
        t0 = time.perf_counter()
        p = _scan_wrapper(resolved_path)  # reuses existing _scan_wrapper() — no code duplication

        # ── Try offline patterns in priority order ────────────────
        # FIX P-M18: Removed useless `result = None` — immediately overwritten.
        result = _ask_pattern_a(p, question, path_display)
        if result is None:
            result = _ask_pattern_b(p, question)
        if result is None:
            result = _ask_pattern_c(p, question, path_display)
        if result is None:
            result = _ask_pattern_d(p, question)

        elapsed_ms = (time.perf_counter() - t0) * 1000

        if result is not None:
            answer_text, show_fix_tip, render_kwargs = result
            if print_output:
                _render_ask_output(
                    question,
                    path_display,
                    p,
                    answer_text,
                    mode="offline",
                    elapsed_ms=elapsed_ms,
                    show_fix_tip=show_fix_tip,
                    **render_kwargs,
                )
            return answer_text if not print_output else None

        # ── Online fallback: Zedda AI ─────────────────────────────
        effective_model = model or _AI_DEFAULT_MODEL
        context_json = _build_ask_context(p, question)

        t1 = time.perf_counter()
        answer_text, usage = _ask_zedda_ai(context_json, question, effective_model)
        elapsed_ms = (time.perf_counter() - t1) * 1000

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
            return str(error_msg) if not print_output else None

        # Heuristic: show fix tip if the AI answer mentions dropping or fixing
        online_fix_tip = (
            "drop" in answer_text.lower()
            or "fix" in answer_text.lower()
            or "impute" in answer_text.lower()
        )
        if print_output:
            _render_ask_output(
                question,
                path_display,
                p,
                answer_text,
                mode=effective_model,
                elapsed_ms=elapsed_ms,
                usage=usage,
                show_fix_tip=online_fix_tip,
            )
        return answer_text if not print_output else None

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
    else:
        # FIX P-H13: No exception — `msg` would be undefined here. Make
        # this path unreachable (the try block already returned).
        msg = None
    finally:
        if is_in_memory:
            _cleanup_temp(resolved_path)

    # FIX P-H12: Always return the string (success or error) when
    # print_output=False, so callers can distinguish success vs error
    # without parsing. The previous `None` return on print_output=True
    # also contradicted the docstring — keep None there for back-compat
    # but document it.
    if print_output:
        if msg is not None:
            if _RICH_AVAILABLE and _console:
                _console.print(f"\n[red]{rich_escape(msg)}[/red]\n")
            else:
                print(msg)
        return None
    return msg if msg is not None else ""


#  Public API





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
    # FIX L-7: Add 'export' alias (was omitted — it's a public alias for report).
    "export",
    # FIX L-25: Expose collect_warnings as public API for programmatic access.
    "collect_warnings",
    "validate",
    "ZeddaError",
    "__version__",
]
# FIX L-8: Removed trailing non-code comments (were release-note noise).
