"""
zedda._ml_ready — ML readiness scoring logic.

FIX Batch 28 / P-M1: Extracted from __init__.py to reduce module size.
Contains the pure scoring logic — no Rich console dependency.
The presentation layer (Rich rendering) stays in __init__.py.

Internal — not part of the public API.
"""

from __future__ import annotations

from typing import Any

from ._warnings import is_outlier_column


# FIX M-35: Extract magic numbers as named constants.
LOOKS_GOOD_MAX_UNIQUE_INT = 15
LOOKS_GOOD_MAX_UNIQUE_STR = 20
LOOKS_GOOD_MAX_NULL_PCT = 5.0


def compute_ml_readiness_score(p: Any) -> dict:
    """Compute an ML readiness score (0-100) and issue list.

    Returns a dict with:
        score: int (0-100)
        issues: list of dicts, each with:
            column: str
            severity: "critical" | "warning" | "info"
            message: str
            fix_code: str
            is_good: bool — True if column is "looks good"
            good_message: str — reason it's good
        drop_cols: list of str — columns recommended for dropping
        recommended_feature_count: int — cols - len(drop_cols)
    """
    score = 100
    issues = []
    drop_cols = []

    for col in p.columns:
        # High nulls = critical (drop)
        if col.null_pct > 50:
            issues.append(
                {
                    "column": col.name,
                    "severity": "critical",
                    "message": f"{col.null_pct:.1f}% nulls, too sparse to trust imputation",
                    "fix_code": f"df = df.drop(columns=[{col.name!r}])",
                    "is_good": False,
                }
            )
            drop_cols.append(col.name)
            score -= 15
            continue

        # Moderate nulls = critical (impute)
        if col.null_pct > 5:
            if col.type_str in ("int", "float"):
                fix = f"df[{col.name!r}] = df[{col.name!r}].fillna(df[{col.name!r}].median())"
            else:
                fix = f"df[{col.name!r}] = df[{col.name!r}].fillna(df[{col.name!r}].mode()[0])"
            issues.append(
                {
                    "column": col.name,
                    "severity": "critical",
                    "message": f"{col.null_pct:.1f}% nulls",
                    "fix_code": fix,
                    "is_good": False,
                }
            )
            score -= 10
            continue

        # ID-like integer column = warning (drop)
        if col.type_str == "int" and col.unique_pct > 95:
            issues.append(
                {
                    "column": col.name,
                    "severity": "warning",
                    "message": f"{col.unique_approx} unique values (ID-like)",
                    "fix_code": f"df = df.drop(columns=[{col.name!r}])",
                    "is_good": False,
                }
            )
            drop_cols.append(col.name)
            score -= 5
            continue

        # ID-like string = warning (drop)
        if col.type_str in ("str", "unknown") and col.unique_pct > 80:
            issues.append(
                {
                    "column": col.name,
                    "severity": "warning",
                    "message": f"{col.unique_approx:,} unique values, ID-like string",
                    "fix_code": f"df = df.drop(columns=[{col.name!r}])",
                    "is_good": False,
                }
            )
            drop_cols.append(col.name)
            score -= 5
            continue

        # High cardinality string = warning (encode)
        if col.type_str in ("str", "unknown") and col.unique_approx > 50:
            issues.append(
                {
                    "column": col.name,
                    "severity": "warning",
                    "message": f"{col.unique_approx:,} unique values, high cardinality",
                    "fix_code": f"df[{col.name!r}] = pd.Categorical(df[{col.name!r}]).codes",
                    "is_good": False,
                }
            )
            score -= 3
            continue

        # Constant column = info (drop)
        if col.is_constant:
            issues.append(
                {
                    "column": col.name,
                    "severity": "info",
                    "message": "Constant value",
                    "fix_code": f"df = df.drop(columns=[{col.name!r}])",
                    "is_good": False,
                }
            )
            drop_cols.append(col.name)
            score -= 2
            continue

        # Outlier = info (clip)
        if is_outlier_column(col):
            issues.append(
                {
                    "column": col.name,
                    "severity": "info",
                    "message": f"Extreme outliers (max {col.val_max:.1f} > 10x mean)",
                    "fix_code": (
                        f"upper = df[{col.name!r}].quantile(0.99); "
                        f"df[{col.name!r}] = df[{col.name!r}].clip(upper=upper)"
                    ),
                    "is_good": False,
                }
            )
            score -= 2
            continue

        # "Looks good" — no issues
        good_msg = _looks_good_message(col)
        issues.append(
            {
                "column": col.name,
                "severity": "info",
                "message": "",
                "fix_code": "",
                "is_good": True,
                "good_message": good_msg,
            }
        )

    score = max(0, min(100, score))
    recommended_feature_count = p.num_cols - len(set(drop_cols))

    return {
        "score": score,
        "issues": issues,
        "drop_cols": list(dict.fromkeys(drop_cols)),  # dedupe, preserve order
        "recommended_feature_count": recommended_feature_count,
    }


def _looks_good_message(col) -> str:
    """Generate a 'looks good' message for a healthy column."""
    # Binary target
    if (
        col.type_str in ("int", "float")
        and col.val_min == 0
        and col.val_max == 1
        and col.unique_approx <= 2
    ):
        return "binary (0/1), good ML target"

    # Low-cardinality categorical
    if col.type_str == "int" and col.unique_approx <= LOOKS_GOOD_MAX_UNIQUE_INT:
        return f"{col.unique_approx} unique values, good categorical feature"

    if col.type_str == "str" and col.unique_approx <= LOOKS_GOOD_MAX_UNIQUE_STR:
        return f"{col.unique_approx} unique values, good categorical feature"

    # Clean numeric
    if col.type_str in ("int", "float") and col.null_pct < LOOKS_GOOD_MAX_NULL_PCT:
        return f"clean numeric (nulls={col.null_pct:.1f}%)"

    return "no issues detected"


def ml_ready(
    path: Any,
    target: str | None = None,
    sample_size: int | None = None,
    correlate: bool = False,
) -> None:
    """
    Check if a dataset is ready for Machine Learning.

    Provides a score (0-100) with a visual progress bar, Target Column section,
    and Feature Verdict Table with plain-English action recommendations.

    Args:
        path (str): Path to a ``.csv``, ``.parquet``, or ``.arrow`` file.
        target (str, optional): Target/label column name.
        sample_size (int, optional): Max rows to sample.
        correlate (bool, optional): Whether to compute correlation matrix.

    Example::

        import zedda as zd
        zd.ml_ready("data.csv", target="churn")
    """
    from ._engine import scan
    from ._errors import ZeddaError
    from ._format import safe_symbol, section_header, render_quality_bar, quality_label
    from ._warnings import detect_column_issues, get_fix_action, is_outlier_column
    import time
    from pathlib import Path

    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box
        from rich.markup import escape as rich_escape
        _console = Console()
        _RICH_AVAILABLE = True
    except ImportError:
        _console = None
        _RICH_AVAILABLE = False

    if not _RICH_AVAILABLE or _console is None:
        raise ZeddaError(
            "Rich is required for terminal output. Install with: pip install rich"
        )

    t0 = time.perf_counter()
    p = scan(path, sample_size=sample_size, correlate=correlate)
    total_ms = (time.perf_counter() - t0) * 1000

    file_name = getattr(p, "file_name", str(path))
    scan_str = (
        f"{total_ms / 1000:.1f} sec" if total_ms >= 10_000 else f"{total_ms:.0f} ms"
    )

    crit_sym = safe_symbol("✗", "[X]")
    warn_sym = safe_symbol("⚠", "[!]")
    check_sym = safe_symbol("✓", "[OK]")
    bullet = safe_symbol("·", "-")

    # Header
    _console.print(
        f"\n[bold blue]zedda[/bold blue] [dim]v0.4.8[/dim]  {bullet}  "
        f"[bold]ml_ready mode[/bold]\n"
    )
    _console.print(
        f"[dim]Scanning[/dim]   [cyan]{file_name}[/cyan]   ...  {scan_str}\n"
    )

    # ML Readiness Score
    readiness_data = compute_ml_readiness_score(p)
    score = readiness_data["score"]

    # Base quality score
    base_score = 100
    base_score -= min(40, int(p.overall_null_pct * 2))
    high_null_cols = sum(1 for c in p.columns if c.has_high_nulls)
    base_score -= min(20, high_null_cols * 5)
    constant_cols = sum(1 for c in p.columns if c.is_constant)
    base_score -= min(20, constant_cols * 10)
    outlier_cols = sum(1 for c in p.columns if is_outlier_column(c))
    base_score -= min(20, outlier_cols * 3)
    base_score = max(0, min(100, base_score))

    bar = render_quality_bar(score)
    color, label = quality_label(score)

    _console.print(section_header("ML Readiness Score"))
    _console.print(f"  Base Data Quality score : {base_score} / 100")
    score_diff = score - base_score
    diff_str = f"({score_diff:+} pts from base)" if score_diff != 0 else ""
    _console.print(
        f"  [{color}]ML Readiness score      : {score} / 100  {bar}  {label}  {diff_str}[/{color}]\n"
    )

    # Target Column
    _console.print(section_header("Target Column"))
    detected_target = None
    if target:
        target_col = next((c for c in p.columns if c.name == target), None)
        if target_col:
            detected_target = target_col.name
            _console.print(
                f"  Target       : [bold cyan]'{rich_escape(target)}'[/bold cyan] (using specified target)"
            )
        else:
            _console.print(
                f"  Target       : [bold yellow]'{rich_escape(target)}'[/bold yellow] (specified target not found)"
            )
    else:
        # Auto-detect binary target candidate
        binary_cand = next(
            (
                c
                for c in p.columns
                if c.type_str in ("int", "float")
                and c.val_min == 0
                and c.val_max == 1
                and (c.unique_exact == 2 or (c.unique_approx is not None and c.unique_approx <= 2))
            ),
            None,
        )
        if binary_cand:
            detected_target = binary_cand.name
            _console.print(
                f"  Target       : [bold cyan]'{rich_escape(binary_cand.name)}'[/bold cyan] (auto-detected binary classification)"
            )
        else:
            _console.print(
                "  Target       : [dim]None specified (unsupervised / feature audit mode)[/dim]"
            )
    _console.print()

    # Feature Verdict Table
    _console.print(section_header("Feature Verdict Table"))
    table_verdict = Table(
        show_header=True,
        header_style="bold white on blue",
        border_style="dim",
        box=box.SIMPLE_HEAVY,
        padding=(0, 1),
    )
    table_verdict.add_column("Feature", style="bold cyan", min_width=12)
    table_verdict.add_column("Verdict", min_width=14)
    table_verdict.add_column("Reason", min_width=25)
    table_verdict.add_column("Action", min_width=20)

    drop_cols = []
    keep_cols = []

    for col in p.columns:
        if detected_target and col.name == detected_target:
            table_verdict.add_row(
                rich_escape(col.name),
                "[bold green]TARGET[/bold green]",
                "Target / label column",
                "Keep as target",
            )
            continue

        issues_found = detect_column_issues(col, p)
        if not issues_found:
            table_verdict.add_row(
                rich_escape(col.name),
                "[bold green]KEEP as-is[/bold green]",
                "Clean distribution",
                "Keep as-is",
            )
            keep_cols.append(col.name)
        else:
            issue = issues_found[0]
            action = get_fix_action(col, issue)
            if action["action_type"] == "drop":
                table_verdict.add_row(
                    rich_escape(col.name),
                    "[bold red]DROP[/bold red]",
                    action["message"],
                    "Drop column",
                )
                drop_cols.append(col.name)
            else:
                act_desc = (
                    "Impute median"
                    if "impute" in action["action_type"]
                    or "missing" in issue.get("message", "").lower()
                    else (
                        "One-hot encode"
                        if "encode" in action["action_type"]
                        or "string" in issue.get("message", "").lower()
                        or "cardinality" in issue.get("message", "").lower()
                        else "Fix issue"
                    )
                )
                table_verdict.add_row(
                    rich_escape(col.name),
                    "[bold yellow]KEEP after fix[/bold yellow]",
                    action["message"],
                    act_desc,
                )
                keep_cols.append(col.name)

    _console.print(table_verdict)
    _console.print()

    # Footer
    recommended = len(keep_cols)
    _console.print(
        f"  [dim]Recommended features for training: {recommended} of {p.num_cols} candidate columns.[/dim]"
    )
    _console.print(
        f'  [dim]Run zd.fix("{file_name}") to generate executable pipeline code.[/dim]\n'
    )

