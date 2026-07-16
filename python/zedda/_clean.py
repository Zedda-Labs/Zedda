"""
zedda._clean — dataset cleaning logic.

FIX Batch 32 / P-M1: Extracted from __init__.py to reduce module size.
Contains the pure cleaning logic — no Rich console dependency.
The presentation layer (Rich rendering) stays in __init__.py.

Internal — not part of the public API.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def create_backup(path: str) -> str | None:
    """Create a backup of the file if it doesn't already exist.

    FIX P-H9: Backup path is {path}.zedda-backup. Only creates a backup
    if one doesn't already exist (idempotent — never overwrites the
    original backup).

    Returns the backup path, or None if no backup was created (e.g.,
    input is a temp file).
    """
    backup_path = str(path) + ".zedda-backup"
    if not Path(backup_path).exists():
        shutil.copy2(path, backup_path)
        return backup_path
    return None  # backup already exists — don't overwrite


def apply_cleaning_fixes(df: Any, p: Any, original_cols: int) -> tuple:
    """Apply all auto-fixable warnings to a DataFrame.

    Returns (cleaned_df, audit_actions, dropped_cols) where:
        cleaned_df: the modified DataFrame
        audit_actions: list of dicts describing each action taken
        dropped_cols: list of column names that were dropped
    """
    import pandas as pd

    audit_actions = []
    dropped_cols = []
    cols_before = len(df.columns)

    for col in p.columns:
        col_name = col.name
        if col_name not in df.columns:
            continue

        col_data = df[col_name]
        null_count = int(col_data.isnull().sum())

        # High nulls → drop
        if col.null_pct > 50 and col.type_str in ("str", "unknown"):
            df = df.drop(columns=[col_name], errors="ignore")
            dropped_cols.append(col_name)
            audit_actions.append(
                {
                    "column": col_name,
                    "action": "drop",
                    "reason": f"{col.null_pct:.1f}% nulls — too sparse",
                }
            )
            continue

        # Moderate nulls → impute
        if null_count > 0 and col.null_pct > 1:
            if col.type_str in ("int", "float"):
                coerced = pd.to_numeric(col_data, errors="coerce")
                coerced_count = max(0, int(coerced.isnull().sum() - null_count))
                fill_val = coerced.median()
                df[col_name] = coerced.fillna(fill_val)
                audit_actions.append(
                    {
                        "column": col_name,
                        "action": "impute",
                        "fill_value": str(fill_val),
                        "cells_fixed": null_count + coerced_count,
                    }
                )
            else:
                # FIX P-M29: Cache mode() result
                m = col_data.mode()
                fill_val = m[0] if not m.empty else "Unknown"
                df[col_name] = col_data.fillna(fill_val)
                audit_actions.append(
                    {
                        "column": col_name,
                        "action": "impute",
                        "fill_value": str(fill_val),
                        "cells_fixed": null_count,
                    }
                )

        # ID-like integer → drop
        if col.type_str == "int" and col.unique_pct > 95:
            df = df.drop(columns=[col_name], errors="ignore")
            dropped_cols.append(col_name)
            audit_actions.append(
                {
                    "column": col_name,
                    "action": "drop",
                    "reason": "ID-like column (unique_pct > 95%)",
                }
            )
            continue

        # High cardinality string → label encode
        if col.type_str in ("str", "unknown") and col.unique_approx > 50:
            df[col_name] = pd.Categorical(df[col_name]).codes
            audit_actions.append(
                {
                    "column": col_name,
                    "action": "encode",
                    "reason": f"{col.unique_approx} unique values — label encoded",
                }
            )
            continue

        # Constant → drop
        if col.is_constant:
            df = df.drop(columns=[col_name], errors="ignore")
            dropped_cols.append(col_name)
            audit_actions.append(
                {
                    "column": col_name,
                    "action": "drop",
                    "reason": "constant value",
                }
            )
            continue

        # Outlier → clip
        from ._warnings import is_outlier_column

        if is_outlier_column(col):
            upper = pd.to_numeric(df[col_name], errors="coerce").quantile(0.99)
            if pd.notna(upper):
                before_max = pd.to_numeric(df[col_name], errors="coerce").max()
                df[col_name] = (
                    pd.to_numeric(df[col_name], errors="coerce")
                    .clip(upper=upper)
                    .infer_objects(copy=False)
                )
                clipped = int(
                    (pd.to_numeric(df[col_name], errors="coerce") != before_max).sum()
                )
                audit_actions.append(
                    {
                        "column": col_name,
                        "action": "clip",
                        "upper_bound": float(upper),
                        "cells_clipped": clipped,
                    }
                )

    return df, audit_actions, dropped_cols


def write_audit_trail(
    audit_path: str,
    source_file: str,
    output_file: str,
    version: str,
    score_before: int,
    score_after: int,
    rows_before: int,
    rows_after: int,
    cols_before: int,
    cols_after: int,
    actions: list,
) -> None:
    """Write the JSON audit trail for a cleaning operation.

    FIX P-H10: Verifies the audit path is in the same directory as the
    output file (prevents path traversal via user-supplied output paths).
    """
    # Verify audit path is in the same directory as output
    if Path(audit_path).resolve().parent != Path(output_file).resolve().parent:
        raise ValueError("Audit path traversal detected — refusing to write.")

    audit_data = {
        "source_file": source_file,
        "output_file": Path(output_file).name,
        "zedda_version": version,
        "score_before": score_before,
        "score_after": score_after,
        "rows_before": rows_before,
        "rows_after": rows_after,
        "cols_before": cols_before,
        "cols_after": cols_after,
        "actions": actions,
    }
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=2, ensure_ascii=False)


def undo_clean(path: str) -> None:
    """Restore a file from its zedda backup."""
    backup = str(path) + ".zedda-backup"
    if not Path(backup).exists():
        from ._resolve import ZeddaError

        raise ZeddaError(
            f"No backup found: '{backup}'\n"
            "Tip: zd.clean() creates a backup before modifying files."
        )
    shutil.copy2(backup, str(path))
