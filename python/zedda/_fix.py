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
        len(null_fixes) + len(outlier_fixes) + len(id_fixes)
        + len(cardinality_fixes) + len(constant_fixes)
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
                df[col.name] = pd.to_numeric(df[col.name], errors="coerce").clip(upper=upper).infer_objects(copy=False)

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

    return df
