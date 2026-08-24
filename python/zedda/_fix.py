"""
zedda._fix — fix code generation logic.

FIX Batch 29 / P-M1: Extracted from __init__.py to reduce module size.
Contains the pure fix-generation logic — no Rich console dependency.
The presentation layer (Rich rendering) stays in __init__.py.

Internal — not part of the public API.
"""

from __future__ import annotations

from typing import Any

from ._warnings import is_outlier_column, detect_column_issues, get_fix_action
from ._format import safe_col_name


def generate_fix_code(p: Any) -> dict:
    """Generate copy-paste-ready pandas fix code for all detected issues.

    Returns a dict with:
        null_fixes: list of (display_line, code_line) tuples
        outlier_fixes: list of (display_line, code_line) tuples
        id_fixes: list of (display_line, code_line) tuples
        cardinality_fixes: list of (display_line, code_line) tuples
        constant_fixes: list of (display_line, code_line) tuples
        all_code: list of str — all fix code lines for the copy-paste block
        n_issues: int — total number of issues found
    """
    null_fixes = []
    outlier_fixes = []
    id_fixes = []
    cardinality_fixes = []
    constant_fixes = []
    all_code = []

    for col in p.columns:
        issues = detect_column_issues(col, p)
        for issue in issues:
            action = get_fix_action(col, issue)
            display_line = action.get("message", "")
            code_line = action.get("fix_code", "")

            if not code_line:
                continue

            itype = issue["type"]

            if itype in ("high_nulls", "moderate_nulls"):
                null_fixes.append((display_line, code_line))
            elif itype == "outlier":
                outlier_fixes.append((display_line, code_line))
            elif itype in ("id_like", "id_like_string"):
                id_fixes.append((display_line, code_line))
            elif itype == "high_cardinality":
                cardinality_fixes.append((display_line, code_line))
            elif itype == "constant":
                constant_fixes.append((display_line, code_line))

            all_code.append(code_line)

    n_issues = (
        len(null_fixes)
        + len(outlier_fixes)
        + len(id_fixes)
        + len(cardinality_fixes)
        + len(constant_fixes)
    )

    return {
        "null_fixes": null_fixes,
        "outlier_fixes": outlier_fixes,
        "id_fixes": id_fixes,
        "cardinality_fixes": cardinality_fixes,
        "constant_fixes": constant_fixes,
        "all_code": all_code,
        "n_issues": n_issues,
    }


def apply_fixes_to_dataframe(df: Any, p: Any) -> Any:
    """Apply all detected fixes to a pandas DataFrame in-place.

    FIX P-C2: Uses clip-at-99th-percentile for outliers (not log1p).
    FIX P-C3: Guards mode() against empty Series.
    FIX P-M27: Reuses _is_outlier_column predicate.

    Returns the modified DataFrame.
    """
    import pandas as pd

    # Apply null fixes
    for col in p.columns:
        if col.null_pct > 1:
            if col.null_pct > 50 and col.type_str in ("str", "unknown"):
                df = df.drop(columns=[col.name], errors="ignore")
            elif col.type_str in ("int", "float"):
                coerced = pd.to_numeric(df[col.name], errors="coerce")
                df[col.name] = coerced.fillna(coerced.median())
            elif col.type_str in ("str", "unknown"):
                m = df[col.name].mode()
                if not m.empty:
                    df[col.name] = df[col.name].fillna(m[0])

    # Apply outlier fixes (clip, not log1p — FIX P-C2)
    for col in p.columns:
        if is_outlier_column(col) and col.name in df.columns:
            upper = pd.to_numeric(df[col.name], errors="coerce").quantile(0.99)
            if pd.notna(upper):
                df[col.name] = (
                    pd.to_numeric(df[col.name], errors="coerce")
                    .clip(upper=upper)
                    .infer_objects(copy=False)
                )

    # Apply ID column drops
    id_cols = [
        col.name for col in p.columns if col.type_str == "int" and col.unique_pct > 95
    ]
    if id_cols:
        df = df.drop(columns=id_cols, errors="ignore")

    # Apply encoding fixes
    for col in p.columns:
        if col.type_str in ("str", "unknown") and col.unique_approx > 50:
            if col.name in df.columns:
                df[col.name] = pd.Categorical(df[col.name]).codes

    return df


def fix(
    path: Any,
    apply: bool = False,
    sample_size: int | None = None,
    correlate: bool = False,
) -> Any:
    """
    Scan a dataset and generate copy-paste-ready pandas fix code.

    Automatically detects the most common data quality problems and
    prints grouped, actionable pandas snippets you can paste directly
    into your data preparation notebook or script.
    """
    from ._engine import scan
    from ._errors import ZeddaError
    from ._format import safe_symbol
    from pathlib import Path

    try:
        from rich.console import Console
        from rich.panel import Panel

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

    null_fixes = []
    outlier_fixes = []
    id_col_fixes = []
    encoding_fixes = []

    for col in p.columns:
        issues = detect_column_issues(col, p)
        if not issues:
            continue

        for issue in issues:
            action = get_fix_action(col, issue)
            arrow_r = safe_symbol("→", "->")
            display_line = (
                f"  [cyan]{action['display']}[/cyan]  "
                f"[dim]{arrow_r} {action['comment']} {arrow_r} {action['fix_action'].split('—')[0].strip(' .').lower()}[/dim]"
            )
            code_line = f"{action['fix_code']}  # {action['comment']}"

            if (
                action["action_type"] == "drop"
                and issue["type"] == "high_nulls"
                or action["action_type"] == "impute"
            ):
                null_fixes.append((display_line, code_line))
            elif action["action_type"] == "clip":
                outlier_fixes.append((display_line, code_line))
            elif action["action_type"] == "drop" and issue["type"] != "high_nulls":
                id_col_fixes.append((display_line, code_line))
            elif action["action_type"] == "encode":
                encoding_fixes.append((display_line, code_line))

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

    n_issues = len(all_fixes)
    summary = (
        f"[bold]{n_issues} issue{'s' if n_issues > 1 else ''} found[/bold] "
        f"across [cyan]{p.num_cols}[/cyan] columns.\n"
        f"[dim]Scroll down for the full copy-paste block.[/dim]"
    )
    file_name = getattr(p, "file_name", str(path))
    _console.print(
        Panel(
            summary,
            title=f"[bold yellow]zd.fix() - {file_name}[/bold yellow]",
            border_style="yellow",
            expand=False,
        )
    )

    sq_icon = safe_symbol("◼", "[*]")
    if null_fixes:
        _console.print(
            f"\n[bold red]{sq_icon}  MISSING VALUES[/bold red]  "
            "[dim](fills nulls with median / mode)[/dim]"
        )
        for display, _ in null_fixes:
            _console.print(display)

    if outlier_fixes:
        _console.print(
            f"\n[bold magenta]{sq_icon}  OUTLIERS[/bold magenta]  "
            "[dim](log1p shrinks extreme right-skewed values)[/dim]"
        )
        for display, _ in outlier_fixes:
            _console.print(display)

    if id_col_fixes:
        _console.print(
            f"\n[bold blue]{sq_icon}  ID COLUMNS[/bold blue]  "
            "[dim](high-uniqueness integers - useless for ML)[/dim]"
        )
        for display, _ in id_col_fixes:
            _console.print(display)

    if encoding_fixes:
        _console.print(
            f"\n[bold cyan]{sq_icon}  ENCODING[/bold cyan]  "
            "[dim](high-cardinality strings -> numeric codes)[/dim]"
        )
        for display, _ in encoding_fixes:
            _console.print(display)

    _console.print(
        "\n[bold]Copy-Paste Block:[/bold]  "
        "[dim](paste this into your notebook or script)[/dim]"
    )

    needs_numpy = bool(outlier_fixes)
    needs_pandas = bool(encoding_fixes)
    if needs_numpy:
        _console.print("[dim]import numpy as np[/dim]")
    if needs_pandas:
        _console.print("[dim]import pandas as pd[/dim]")

    for _, code in all_fixes:
        _console.print(f"  [cyan]{code}[/cyan]")
    _console.print()

    if apply:
        try:
            import numpy as np
            import pandas as pd
        except ImportError:
            _console.print(
                "[red]pandas / numpy not installed - cannot apply fixes.[/red]\n"
                "Run: pip install pandas numpy"
            )
            return None

        if hasattr(path, "to_pandas"):
            df = path.to_pandas()
        elif hasattr(path, "copy") and not isinstance(path, (str, Path)):
            df = path.copy()
        else:
            resolved_str = str(path)
            if Path(resolved_str).suffix.lower() == ".csv":
                df = pd.read_csv(resolved_str)
            else:
                df = pd.read_parquet(resolved_str)

        return apply_fixes_to_dataframe(df, p)

    return None
