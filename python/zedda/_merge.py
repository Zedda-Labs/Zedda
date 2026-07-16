"""
zedda._merge — dataset merge logic.

FIX Batch 31 / P-M1: Extracted from __init__.py to reduce module size.
Contains the pure merge logic — no Rich console dependency.
The presentation layer (Rich rendering) stays in __init__.py.

Internal — not part of the public API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def compute_overlap_count(dataframes: list, common_cols: list) -> int:
    """Count duplicate rows across all DataFrames (based on common columns).

    FIX P-H7: Replaces the O(N²) pair-wise merge approach with a single
    O(N) pass: concat all DataFrames, then count duplicates.

    Returns the number of duplicate rows found.
    """
    if len(dataframes) < 2 or not common_cols:
        return 0
    import pandas as pd

    combined = pd.concat(dataframes, ignore_index=True)
    # Count duplicates (excluding the first occurrence)
    return int(combined.duplicated(subset=common_cols, keep="first").sum())


def compute_schema_mismatches(
    dataframes: list,
    file_names: list,
) -> list:
    """Check schema consistency across DataFrames.

    Returns a list of dicts, each with:
        file: str — file name with the mismatch
        missing: list of str — columns missing vs the reference (file 0)
        extra: list of str — extra columns vs the reference
    """
    if len(dataframes) < 2:
        return []

    ref_cols = set(dataframes[0].columns)
    mismatches = []
    for i, df in enumerate(dataframes[1:], 1):
        this_cols = set(df.columns)
        missing = sorted(ref_cols - this_cols)
        extra = sorted(this_cols - ref_cols)
        if missing or extra:
            mismatches.append(
                {
                    "file": file_names[i],
                    "missing": missing,
                    "extra": extra,
                }
            )
    return mismatches


def combine_dataframes(
    dataframes: list,
    common_cols: list,
    file_names: list,
) -> Any:
    """Combine DataFrames with dedup and source tracking.

    FIX P-H8: Dedup uses common_cols as subset (not ALL columns).
    Adds a 'zedda_source_file' column for tracking provenance.

    Returns the combined DataFrame.
    """
    import pandas as pd

    # Add source tracking column
    for df, name in zip(dataframes, file_names):
        df["zedda_source_file"] = name

    combined = pd.concat(dataframes, ignore_index=True)

    # Dedup on common columns (not ALL columns — FIX P-H8)
    if common_cols:
        before = len(combined)
        combined = combined.drop_duplicates(subset=common_cols, keep="first")
        deduped = before - len(combined)
    else:
        deduped = 0

    return combined, deduped
