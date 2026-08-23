"""
zedda._profile_print — Rich terminal output for profile()

Extracted from __init__.py during Phase 5.11 migration.
Internal module.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ._constants import sampled_info_get as _sampled_info_get
from ._format import (
    format_num as _format_num,
    format_ci as _format_ci,
    format_scan_time as _format_scan_time,
    quality_label as _quality_label,
    render_quality_bar as _render_quality_bar,
    render_shape_descriptor as _render_shape_descriptor,
    safe_symbol as _safe_symbol,
)
from ._warnings import (
    collect_warnings as _collect_warnings,
    is_outlier_column as _is_outlier_column,
)

def _collect_warnings_legacy(p: Any) -> list:
    """Legacy wrapper: return old-format warnings for _print_report() compatibility."""
    new_warnings = _collect_warnings(p)
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

# Rich for terminal output
try:
    from rich import box
    from rich.console import Console
    from rich.markup import escape as rich_escape
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False

    def rich_escape(s: str) -> str:  # type: ignore
        return s

_console = Console() if _RICH_AVAILABLE else None

def _quality_score(p, original_cols: int | None = None) -> int:
    """Compute a 0-100 data quality score from the profile object."""
    score = 100
    if original_cols is not None and p.num_cols < original_cols:
        dropped = original_cols - p.num_cols
        score -= min(20, dropped * 5)
    score -= min(40, int(p.overall_null_pct * 2))
    high_null_cols = sum(1 for c in p.columns if c.has_high_nulls)
    score -= min(20, high_null_cols * 5)
    constant_cols = sum(1 for c in p.columns if c.is_constant)
    score -= min(20, constant_cols * 10)
    outlier_cols = sum(1 for c in p.columns if _is_outlier_column(c))
    score -= min(20, outlier_cols * 3)
    return max(0, min(100, score))

def _quality_score_display(p: Any, console) -> None:
    """Print a visual quality score bar to the console."""
    score = _quality_score(p)
    bar = _render_quality_bar(score)
    color, label = _quality_label(score)

    hints = []
    high_null = sum(1 for c in p.columns if c.has_high_nulls)
    constant = sum(1 for c in p.columns if c.is_constant)
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

    if getattr(p, "correlation_skipped", False):
        console.print(
            f"\n[yellow]{warn_icon} Warning:[/yellow] Correlation matrix skipped due to high numeric column count.\n"
            "   Pass [bold]correlate=True[/bold] to force calculation (may take minutes)."
        )

def _print_report(p: Any) -> None:
    if not _RICH_AVAILABLE or _console is None:
        _print_plain(p)
        return

    from .__init__ import __version__

    title = "[bold blue]Dataset Overview[/bold blue]"
    sampled_lines = ""
    if p.is_sampled:
        title += "  [yellow]⚡ SAMPLED[/yellow]"
        scanned_rows, total_rows = _sampled_info_get(
            p.file_path, (p.num_rows, p.num_rows)
        )
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

    _quality_score_display(p, _console)

    numeric_cols = [c for c in p.columns if c.type_str in ("int", "float", "bool")]
    cat_cols = [c for c in p.columns if c.type_str not in ("int", "float", "bool")]

    truncated_names = []

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

    _correlation_alerts(p, _console)

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
    from .__init__ import __version__
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
        mean_s = _format_num(col.mean, col.type_str == "int") if col.type_str in ("int", "float") else "-"
        col_name = col.name if len(col.name) <= 12 else col.name[:10] + ".."
        print(f"{col_name:<14}{col.type_str:<8}{col.null_pct:.1f}%     {mean_s}")
