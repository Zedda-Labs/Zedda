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

    if col.null_pct > 50:
        issues.append({"type": "high_nulls", "severity": "critical", "action": "drop"})

    if col.null_pct > 5:
        issues.append(
            {"type": "moderate_nulls", "severity": "critical", "action": "impute"}
        )

    if col.type_str == "int" and col.unique_pct > 95:
        issues.append({"type": "id_like", "severity": "critical", "action": "drop"})

    if col.type_str in ("str", "unknown") and col.unique_pct > 80:
        issues.append(
            {"type": "id_like_string", "severity": "warning", "action": "drop"}
        )

    if col.type_str in ("str", "unknown") and col.unique_approx > 50:
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
    }

    if itype == "high_nulls":
        res["message"] = f"{col.null_pct:.1f}% nulls"
        res["fix_action"] = "Too sparse to impute reliably."
        res["fix_code"] = f"df = df.drop(columns=[{safe}])"
        res["comment"] = f"{col.null_pct:.1f}% nulls — too sparse to impute"
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
    elif itype == "id_like":
        res["message"] = f"{col.unique_pct:.1f}% unique, ID column"
        res["fix_action"] = "No predictive signal — drop before training."
        res["fix_code"] = f"df = df.drop(columns=[{safe}])"
        res["comment"] = f"{col.unique_pct:.1f}% unique values — ID column"
    elif itype == "id_like_string":
        res["message"] = f"{col.unique_approx:,} unique values, ID-like string"
        res["fix_action"] = "Drop before training — no predictive signal"
        res["fix_code"] = f"df = df.drop(columns=[{safe}])"
        res["comment"] = f"{col.unique_pct:.1f}% unique values — ID-like string"
    elif itype == "high_cardinality":
        res["message"] = f"{col.unique_approx:,} unique values, high cardinality"
        res["fix_action"] = "Label encode into integers."
        res["fix_code"] = f"df[{safe}] = pd.Categorical(df[{safe}]).codes"
        res["comment"] = f"{col.unique_approx} unique values"
    elif itype == "constant":
        res["message"] = "Constant value"
        res["fix_action"] = "No variance — drop column."
        res["fix_code"] = f"df = df.drop(columns=[{safe}])"
        res["comment"] = "constant value"
    elif itype == "outlier":
        res["message"] = f"Extreme outliers (max {col.val_max:.1f} > 10x mean)"
        res["fix_action"] = "Clip at 99th percentile."
        res["fix_code"] = (
            f"upper = df[{safe}].quantile(0.99); "
            f"df[{safe}] = df[{safe}].clip(upper=upper)"
        )
        res["comment"] = f"max={col.val_max:.1f} is >10x mean"

    return res


def collect_warnings(p: Any) -> list:
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
