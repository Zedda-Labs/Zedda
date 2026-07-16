"""
zedda._compare — dataset comparison logic (schema, drift, verdict).

FIX Batch 27 / P-M1: Extracted from __init__.py to reduce module size.
Contains the pure comparison logic — no Rich console dependency.
The presentation layer (Rich rendering) stays in __init__.py.

Internal — not part of the public API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def compute_schema_diff(
    cols_a: list,
    cols_b: list,
    name_a: str = "A",
    name_b: str = "B",
) -> dict:
    """Compute schema differences between two column lists.

    Returns a dict with:
        missing_in_b: list of column names present in A but not B
        missing_in_a: list of column names present in B but not A
        type_mismatches: list of (col_name, type_a, type_b) tuples
        types_match: int — number of columns with matching types
        total_compared: int — total columns compared
    """
    names_a = {c.name: c for c in cols_a}
    names_b = {c.name: c for c in cols_b}
    set_a = set(names_a.keys())
    set_b = set(names_b.keys())

    missing_in_b = sorted(set_a - set_b)
    missing_in_a = sorted(set_b - set_a)
    common = set_a & set_b

    type_mismatches = []
    types_match = 0
    for name in common:
        ta = names_a[name].type_str
        tb = names_b[name].type_str
        if ta != tb:
            type_mismatches.append((name, ta, tb))
        else:
            types_match += 1

    return {
        "missing_in_b": missing_in_b,
        "missing_in_a": missing_in_a,
        "type_mismatches": type_mismatches,
        "types_match": types_match,
        "total_compared": len(common),
    }


def compute_distribution_shift(
    cols_a: list,
    cols_b: list,
) -> list:
    """Compute distribution shift for common numeric columns.

    Returns a list of dicts, each with:
        col_name: str
        mean_a, mean_b: float
        shift_pct: float — percentage change relative to mean_a
        shift_abs: float — absolute change
        is_stable: bool — True if shift_pct < 5%
        is_shift: bool — True if shift_pct >= 10%
    """
    names_a = {c.name: c for c in cols_a}
    names_b = {c.name: c for c in cols_b}
    common = sorted(set(names_a.keys()) & set(names_b.keys()))

    results = []
    for name in common:
        ca = names_a[name]
        cb = names_b[name]
        # Only compare numeric columns
        if ca.type_str not in ("int", "float") or cb.type_str not in ("int", "float"):
            continue
        # Skip ID-like columns (unique_pct > 95)
        if ca.unique_pct > 95 or cb.unique_pct > 95:
            continue
        # Skip binary target columns (0/1)
        if ca.val_min == 0 and ca.val_max == 1 and ca.unique_approx <= 2:
            continue

        mean_a = ca.mean
        mean_b = cb.mean
        shift_abs = mean_b - mean_a

        # FIX M-32: Handle negative/zero means correctly
        if mean_a > 0:
            shift_pct = (shift_abs / mean_a) * 100.0
        elif mean_a < 0:
            shift_pct = (shift_abs / abs(mean_a)) * 100.0
        else:
            # mean_a == 0
            shift_pct = 0.0 if mean_b == 0 else float("inf")

        is_stable = abs(shift_pct) < 5.0
        is_shift = abs(shift_pct) >= 10.0

        results.append(
            {
                "col_name": name,
                "mean_a": mean_a,
                "mean_b": mean_b,
                "shift_pct": shift_pct,
                "shift_abs": shift_abs,
                "is_stable": is_stable,
                "is_shift": is_shift,
            }
        )

    return results


def compute_verdict(
    schema_diff: dict,
    shifts: list,
) -> dict:
    """Compute the overall comparison verdict.

    Returns a dict with:
        verdict: "PASS" | "REVIEW" | "FAIL"
        critical_errors: int
        warnings: int
        safe_to_train: bool
        message: str — human-readable summary
    """
    critical_errors = 0
    warnings = 0

    # Missing columns = critical (unless it's a binary target)
    for col in schema_diff["missing_in_b"]:
        critical_errors += 1

    # Type mismatches = critical
    critical_errors += len(schema_diff["type_mismatches"])

    # Distribution shifts = warning
    for s in shifts:
        if s["is_shift"]:
            warnings += 1

    if critical_errors > 0:
        verdict = "FAIL"
        safe_to_train = False
    elif warnings > 0:
        verdict = "REVIEW"
        safe_to_train = True  # review but probably OK
    else:
        verdict = "PASS"
        safe_to_train = True

    parts = []
    if critical_errors:
        parts.append(
            f"{critical_errors} critical issue{'s' if critical_errors != 1 else ''}"
        )
    if warnings:
        parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
    if not parts:
        parts.append("no issues")

    message = f"{verdict} — {', '.join(parts)}"

    return {
        "verdict": verdict,
        "critical_errors": critical_errors,
        "warnings": warnings,
        "safe_to_train": safe_to_train,
        "message": message,
    }


def looks_like_target_column(col_name: str) -> bool:
    """Check if a column name looks like a binary ML target.

    Used to downgrade 'missing in test' from critical to warning when
    the missing column is the target (expected in ML train/test splits).
    """
    name_lower = col_name.lower()
    target_names = {
        "survived",
        "target",
        "label",
        "y",
        "class",
        "outcome",
        "is_",
        "has_",
    }
    return any(name_lower == t or name_lower.startswith(t) for t in target_names)
