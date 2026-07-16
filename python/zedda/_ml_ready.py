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
            issues.append({
                "column": col.name,
                "severity": "critical",
                "message": f"{col.null_pct:.1f}% nulls, too sparse to trust imputation",
                "fix_code": f"df = df.drop(columns=[{col.name!r}])",
                "is_good": False,
            })
            drop_cols.append(col.name)
            score -= 15
            continue

        # Moderate nulls = critical (impute)
        if col.null_pct > 5:
            if col.type_str in ("int", "float"):
                fix = f"df[{col.name!r}] = df[{col.name!r}].fillna(df[{col.name!r}].median())"
            else:
                fix = f"df[{col.name!r}] = df[{col.name!r}].fillna(df[{col.name!r}].mode()[0])"
            issues.append({
                "column": col.name,
                "severity": "critical",
                "message": f"{col.null_pct:.1f}% nulls",
                "fix_code": fix,
                "is_good": False,
            })
            score -= 10
            continue

        # ID-like integer column = warning (drop)
        if col.type_str == "int" and col.unique_pct > 95:
            issues.append({
                "column": col.name,
                "severity": "warning",
                "message": f"{col.unique_approx} unique values (ID-like)",
                "fix_code": f"df = df.drop(columns=[{col.name!r}])",
                "is_good": False,
            })
            drop_cols.append(col.name)
            score -= 5
            continue

        # ID-like string = warning (drop)
        if col.type_str in ("str", "unknown") and col.unique_pct > 80:
            issues.append({
                "column": col.name,
                "severity": "warning",
                "message": f"{col.unique_approx:,} unique values, ID-like string",
                "fix_code": f"df = df.drop(columns=[{col.name!r}])",
                "is_good": False,
            })
            drop_cols.append(col.name)
            score -= 5
            continue

        # High cardinality string = warning (encode)
        if col.type_str in ("str", "unknown") and col.unique_approx > 50:
            issues.append({
                "column": col.name,
                "severity": "warning",
                "message": f"{col.unique_approx:,} unique values, high cardinality",
                "fix_code": f"df[{col.name!r}] = pd.Categorical(df[{col.name!r}]).codes",
                "is_good": False,
            })
            score -= 3
            continue

        # Constant column = info (drop)
        if col.is_constant:
            issues.append({
                "column": col.name,
                "severity": "info",
                "message": "Constant value",
                "fix_code": f"df = df.drop(columns=[{col.name!r}])",
                "is_good": False,
            })
            drop_cols.append(col.name)
            score -= 2
            continue

        # Outlier = info (clip)
        if is_outlier_column(col):
            issues.append({
                "column": col.name,
                "severity": "info",
                "message": f"Extreme outliers (max {col.val_max:.1f} > 10x mean)",
                "fix_code": (
                    f"upper = df[{col.name!r}].quantile(0.99); "
                    f"df[{col.name!r}] = df[{col.name!r}].clip(upper=upper)"
                ),
                "is_good": False,
            })
            score -= 2
            continue

        # "Looks good" — no issues
        good_msg = _looks_good_message(col)
        issues.append({
            "column": col.name,
            "severity": "info",
            "message": "",
            "fix_code": "",
            "is_good": True,
            "good_message": good_msg,
        })

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
    if (col.type_str in ("int", "float")
        and col.val_min == 0
        and col.val_max == 1
        and col.unique_approx <= 2):
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
