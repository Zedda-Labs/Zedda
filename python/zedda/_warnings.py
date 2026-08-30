"""
zedda._warnings — issue detection and warning collection logic.

FIX P-M2 / Batch 7: Extracted from __init__.py to reduce module size
and isolate the warning/issue-detection logic for unit testing.
Internal — not part of the public API.
"""

from __future__ import annotations

from typing import Any


def is_outlier_column(col) -> bool:
    """Check if a column has extreme outlier characteristics.

    Returns True when max >> 10x mean AND the column is not a ratio/percent
    column (where extreme max is expected).

    FIX P-M2: Replaces 6× duplicated copies of this predicate across
    __init__.py (lines 150-165, 968-978, 999-1009, 1700-1708,
    2162-2169, 3479-3489 in the original).
    """
    return (
        col.type_str in ("int", "float")
        and col.mean > 0
        and col.unique_approx > 5
        and col.val_max > 10
        and col.val_max > col.mean * 10
        and "ratio" not in col.name.lower()
        and "pct" not in col.name.lower()
        and not (col.mean < 2.0)
        and not (col.type_str == "int" and col.unique_approx < 15 and col.val_min >= 0)
        and not (
            col.type_str == "int"
            and col.val_min == 0
            and col.val_max <= col.unique_approx + 5
        )
    )


def detect_column_issues(col, p) -> list:
    """Unified issue detection returning a list of dicts with issue types.

    FIX L-10: Removed the multiple early returns that skipped outlier
    detection. A column can be both sparse AND an outlier — we now
    collect all applicable issues, then sort/prioritize at the end.
    """
    issues = []

    if getattr(col, "type_mismatch_count", 0) > 0:
        issues.append(
            {"type": "type_mismatch", "severity": "critical", "action": "drop_invalid"}
        )

    if col.null_pct > 50:
        issues.append({"type": "high_nulls", "severity": "critical", "action": "drop"})
    elif col.null_pct > 5:
        issues.append(
            {"type": "moderate_nulls", "severity": "critical", "action": "impute"}
        )

    if col.type_str == "int" and col.unique_pct > 95:
        issues.append({"type": "id_like", "severity": "critical", "action": "drop"})

    if col.type_str in ("str", "unknown") and col.unique_pct > 80:
        issues.append(
            {"type": "id_like_string", "severity": "warning", "action": "drop"}
        )
    elif col.type_str in ("str", "unknown") and col.unique_approx > 50:
        issues.append(
            {"type": "high_cardinality", "severity": "warning", "action": "encode"}
        )

    if col.is_constant:
        issues.append({"type": "constant", "severity": "info", "action": "drop"})

    if is_outlier_column(col):
        issues.append({"type": "outlier", "severity": "info", "action": "clip"})

    return issues


def get_fix_action(col, issue: dict) -> dict:
    """Given a column and an issue dict, returns formatting strings and pandas code.

    FIX L-9: Candidate for dispatch dict in future refactor — 60-line
    if/elif is acceptable for now since each branch is distinct.
    """
    # Import locally to avoid circular import at module load time.
    from ._format import safe_col_name
    from rich.markup import escape as rich_escape

    safe = safe_col_name(col.name)
    display = rich_escape(col.name)
    itype = issue["type"]

    res = {
        "icon": "✗"
        if issue["severity"] == "critical"
        else ("⚠" if issue["severity"] == "warning" else "ℹ"),
        "column": col.name,
        "display": display,
        "safe": safe,
        "severity": issue["severity"],
        "action_type": issue["action"],
        "is_suggestion": True,
    }

    if itype == "type_mismatch":
        res["message"] = (
            f"{col.type_mismatch_count} values didn't match the column's detected type and were excluded"
        )
        res["fix_action"] = "Values coerced to null due to type mismatch."
        res["fix_code"] = (
            f"# No action needed, ZEDDA automatically coerced {col.type_mismatch_count} invalid values to null"
        )
        res["comment"] = f"{col.type_mismatch_count} type mismatches excluded"
        res["evidence_metric"] = {"type_mismatch_count": col.type_mismatch_count}
    elif itype == "high_nulls":
        res["message"] = f"{col.null_pct:.1f}% nulls"
        res["fix_action"] = "Too sparse to impute reliably."
        res["fix_code"] = f"df = df.drop(columns=[{safe}])"
        res["comment"] = f"{col.null_pct:.1f}% nulls — too sparse to impute"
        res["evidence_metric"] = {"null_pct": col.null_pct}
    elif itype == "moderate_nulls":
        res["message"] = f"{col.null_pct:.1f}% nulls"
        if col.type_str in ("int", "float"):
            res["fix_action"] = "Impute with median."
            res["fix_code"] = (
                f"df[{safe}] = pd.to_numeric(df[{safe}], errors='coerce'); "
                f"df[{safe}] = df[{safe}].fillna(df[{safe}].median())"
            )
        else:
            res["fix_action"] = "Impute with mode."
            res["fix_code"] = f"df[{safe}] = df[{safe}].fillna(df[{safe}].mode()[0])"
        res["comment"] = f"{col.null_pct:.1f}% nulls"
        res["evidence_metric"] = {"null_pct": col.null_pct}
    elif itype == "id_like":
        res["message"] = f"{col.unique_pct:.1f}% unique, ID column"
        res["fix_action"] = "No predictive signal — drop before training."
        res["fix_code"] = f"df = df.drop(columns=[{safe}])"
        res["comment"] = f"{col.unique_pct:.1f}% unique values — ID column"
        res["evidence_metric"] = {"unique_pct": col.unique_pct}
    elif itype == "id_like_string":
        res["message"] = (
            f"{int(col.unique_approx or 0):,} unique values, ID-like string"
        )
        res["fix_action"] = "Drop before training — no predictive signal"
        res["fix_code"] = f"df = df.drop(columns=[{safe}])"
        res["comment"] = f"{col.unique_pct:.1f}% unique values — ID-like string"
        res["evidence_metric"] = {
            "unique_approx": col.unique_approx,
            "unique_pct": col.unique_pct,
        }
    elif itype == "high_cardinality":
        res["message"] = (
            f"{int(col.unique_approx or 0):,} unique values, high cardinality"
        )
        res["fix_action"] = "Label encode into integers."
        res["fix_code"] = f"df[{safe}] = pd.Categorical(df[{safe}]).codes"
        res["comment"] = f"{int(col.unique_approx or 0):,} unique values"
        res["evidence_metric"] = {"unique_approx": col.unique_approx}
    elif itype == "constant":
        res["message"] = "Constant value"
        res["fix_action"] = "No variance — drop column."
        res["fix_code"] = f"df = df.drop(columns=[{safe}])"
        res["comment"] = "constant value"
        res["evidence_metric"] = {"is_constant": True}
    elif itype == "outlier":
        res["message"] = f"Extreme outliers (max {col.val_max:.1f} > 10x mean)"
        res["fix_action"] = "Clip at 99th percentile."
        res["fix_code"] = (
            f"upper = df[{safe}].quantile(0.99); "
            f"df[{safe}] = df[{safe}].clip(upper=upper)"
        )
        res["comment"] = f"max={col.val_max:.1f} is >10x mean"
        res["evidence_metric"] = {"val_max": col.val_max, "mean": col.mean}

    return res


def collect_warnings(source: Any, sample_size: int | None = None) -> list:
    """Collect structured warnings for a dataset profile or input data.

    Accepts either a DatasetProfile object or a file path / DataFrame.

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
    if (
        hasattr(source, "columns")
        and not hasattr(source, "to_pandas")
        and not hasattr(source, "iloc")
    ):
        p = source
    else:
        from ._engine import scan

        p = scan(source, sample_size=sample_size)

    warn_list = []
    for col in p.columns:
        issues = detect_column_issues(col, p)
        for issue in issues:
            action_dict = get_fix_action(col, issue)
            action_dict["category"] = issue["type"]
            action_dict["auto_fixable"] = True
            warn_list.append(action_dict)
    # Sort: critical first, then warning, then info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    warn_list.sort(key=lambda w: severity_order.get(w["severity"], 9))
    return warn_list


def warnings(
    path: Any,
    sample_size: int | None = None,
    correlate: bool = False,
    show_fixes: bool = False,
) -> None:
    """
    Show ALL warnings for a file with intelligence mode.

    Displays every data quality warning with severity levels,
    inline fix code, a copy-paste fix block, quality score,
    and auto-fixable count.

    Args:
        path (str): Path to a ``.csv``, ``.parquet``, or ``.arrow`` file or DataFrame.
        sample_size (int, optional): Max rows to sample for profiling.
        correlate (bool, optional): Whether to compute correlation matrix.
        show_fixes (bool, optional): Whether to print inline fix code and copy-paste block.

    Example::

        import zedda as zd
        zd.warnings("data.csv")
    """
    from ._engine import scan
    from ._errors import ZeddaError
    from ._format import safe_symbol
    from pathlib import Path

    try:
        from rich.console import Console
        from rich.markup import escape as rich_escape

        _console_default = Console()
        _rich_default = True
    except ImportError:
        _console_default = None
        _rich_default = False

    import sys

    zd_mod = sys.modules.get("zedda")
    rich_avail = (
        getattr(zd_mod, "_RICH_AVAILABLE", _rich_default)
        if zd_mod is not None
        else _rich_default
    )
    console_obj = (
        getattr(zd_mod, "_console", _console_default)
        if zd_mod is not None
        else _console_default
    )

    if not rich_avail or console_obj is None:
        raise ZeddaError(
            "Rich is required for terminal output. Install with: pip install rich"
        )
    _console = console_obj

    p = scan(path, sample_size=sample_size, correlate=correlate)
    file_name = getattr(p, "file_name", str(path))

    all_warnings = collect_warnings(p)

    # Count by severity
    n_critical = sum(1 for w in all_warnings if w["severity"] == "critical")
    n_warning = sum(1 for w in all_warnings if w["severity"] == "warning")
    n_info = sum(1 for w in all_warnings if w["severity"] == "info")
    total = len(all_warnings)

    # Header
    _console.print(
        "\n[bold blue]zedda[/bold blue] [dim]v0.4.8[/dim]  ·  "
        "[bold]warnings mode[/bold]  ·  [dim]intelligence[/dim]\n"
    )

    if not all_warnings:
        _console.print("  [green]✓  No warnings — data looks clean![/green]\n")
        return

    # Severity summary line
    parts = []
    if n_critical:
        parts.append(f"[red]{n_critical} critical[/red]")
    if n_warning:
        parts.append(
            f"[yellow]{n_warning} warning{'s' if n_warning != 1 else ''}[/yellow]"
        )
    if n_info:
        parts.append(f"[blue]{n_info} info[/blue]")
    severity_str = " · ".join(parts)

    _console.print(
        f"[bold]Found {total} issue{'s' if total != 1 else ''}[/bold] · {severity_str}\n"
    )

    crit_icon = safe_symbol("✗", "[X]")
    warn_icon = safe_symbol("⚠", "[!]")
    info_icon = safe_symbol("ℹ", "[i]")
    severity_labels = {
        "critical": (f"[red]{crit_icon} CRITICAL[/red]", "red"),
        "warning": (f"[yellow]{warn_icon} WARNING [/yellow]", "yellow"),
        "info": (f"[blue]{info_icon} INFO    [/blue]", "blue"),
    }

    arrow_r = safe_symbol("→", "->")
    for w in all_warnings:
        label, color = severity_labels.get(w["severity"], ("[dim]?[/dim]", "dim"))
        _console.print(
            f"{label}  [cyan]'{rich_escape(w['column'])}'[/cyan] — {w['message']}"
        )
        if w.get("fix_action"):
            _console.print(f"   {w['fix_action']}")
        if show_fixes and w.get("fix_code"):
            _console.print(f"   [dim]{arrow_r} Fix: {w['fix_code']}[/dim]")
        _console.print()

    # Copy-Paste Fix Block
    if show_fixes:
        fixable = [w for w in all_warnings if w.get("fix_code")]
        if fixable:
            _console.print("[bold]Copy-Paste Fix Block:[/bold]")
            for w in fixable:
                _console.print(f"  [cyan]{w['fix_code']}[/cyan]")
            _console.print()

    # Summary Footer
    n_auto = sum(1 for w in all_warnings if w.get("auto_fixable"))
    auto_pct = int(n_auto / total * 100) if total > 0 else 0

    _console.print(
        f"[bold]Auto-fixable:[/bold] {n_auto} of {total} ({auto_pct}%)\n"
        f'{arrow_r} [dim]Run zd.fix("{file_name}") to view or generate Pandas fix code.[/dim]\n'
    )


def get_quality_score_metadata(p, original_cols: int | None = None) -> dict[str, Any]:
    """Expose heuristic data quality score and transparent methodology metadata."""
    from ._profile_print import _quality_score_metadata

    return _quality_score_metadata(p, original_cols=original_cols)
