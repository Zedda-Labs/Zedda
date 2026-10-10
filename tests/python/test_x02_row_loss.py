"""
X-02 regression tests: clean() must not silently drop rows or invent imputations.

Root cause: pd.read_csv() default (skip_blank_lines=True, no custom na_values)
has a different null-token set than C++ fast_is_null, causing:
  1. Whitespace-only rows (" ", "\t") are dropped by pandas before clean() sees them.
  2. Tokens like "none", "?", "Null" are NOT null in pandas but ARE null in scan().
  3. clean() reports imputed N cells where N comes from scan() null_count but
     pandas DataFrame has 0 NaN for that column -> audit claim is false.
  4. clean() prints "Rows: N -> N" hiding that rows were silently dropped.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import zedda as zd

from zedda.fasteda_core import is_null_token

TEST_TOKENS = [
    "",
    " ",
    "  \t  ",
    "NA",
    "na",
    "N/A",
    "null",
    "NULL",
    "Null",
    "nan",
    "NaN",
    "none",
    "None",
    "NONE",
    "#N/A",
    "?",
    "unknown",
    "-",
    "--",
    "   ",
    "\t\t",
    " none",
]

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def test_x02a_whitespace_row_not_dropped(tmp_path: Path) -> None:
    """A row whose value is " " (whitespace-only) must survive clean()."""
    src = tmp_path / "x02a.csv"
    src.write_text(
        "id,val\n1,1\n2,none\n3,3\n4, \n5,5\n",
        encoding="utf-8",
    )
    assert sum(1 for _ in src.read_text().splitlines()) - 1 == 5

    profile_before = zd.scan(str(src))
    assert profile_before.num_rows == 5, (
        f"scan() row_count={profile_before.num_rows}, expected 5"
    )

    out = tmp_path / "x02a_clean.csv"
    zd.clean(str(src), output=str(out), dry_run=False, approved=True)

    df_out = pd.read_csv(str(out), keep_default_na=False)
    assert len(df_out) == 5, (
        f"X-02-A FAIL: output has {len(df_out)} rows, expected 5. "
        f"Whitespace-only row was silently dropped."
    )


def test_x02b_audit_imputation_count_is_accurate(tmp_path: Path) -> None:
    """Audit cells_fixed must equal actually-NaN cells in pandas with zedda null tokens."""
    src = tmp_path / "x02b.csv"
    src.write_text("id,val\n1,A\n2,none\n3,B\n", encoding="utf-8")

    out = tmp_path / "x02b_clean.csv"
    zd.clean(str(src), output=str(out), dry_run=False, approved=True)

    audit_candidates = list(tmp_path.glob("*.audit.json"))
    assert audit_candidates, "No audit JSON found after clean()"
    audit = json.loads(audit_candidates[0].read_text())

    df_before = pd.read_csv(
        str(src),
        skip_blank_lines=False,
        na_filter=False,
    )
    import numpy as np
    for c in df_before.columns:
        if pd.api.types.is_object_dtype(df_before[c]) or pd.api.types.is_string_dtype(df_before[c]):
            mask = df_before[c].apply(lambda x: isinstance(x, str) and is_null_token(x))
            df_before.loc[mask, c] = np.nan

    for action in audit.get("actions", []):
        if action.get("action") == "impute":
            col = action["column"]
            cells_fixed = action.get("cells_fixed", 0)
            actual_nan_count = int(df_before[col].isna().sum()) if col in df_before.columns else 0
            assert cells_fixed == actual_nan_count, (
                f"X-02-B FAIL: audit says cells_fixed={cells_fixed} for '{col}', "
                f"but pandas (with zedda tokens) sees {actual_nan_count} NaN."
            )


@pytest.mark.parametrize("null_token", TEST_TOKENS)
def test_x02c_scan_clean_null_token_agreement(tmp_path: Path, null_token: str) -> None:
    """scan() null_count must equal pandas null count when using is_null_token."""
    safe_name = hashlib.md5(null_token.encode()).hexdigest()
    src = tmp_path / f"x02c_{safe_name}.csv"
    src.write_text(
        f"id,val\n1,A\n2,{null_token}\n3,B\n",
        encoding="utf-8",
    )

    profile = zd.scan(str(src))
    val_col = next((c for c in profile.columns if c.name == "val"), None)
    assert val_col is not None

    scan_null_count = val_col.null_count

    df_read = pd.read_csv(
        str(src),
        skip_blank_lines=False,
        na_filter=False,
    )
    import numpy as np
    for c in df_read.columns:
        if pd.api.types.is_object_dtype(df_read[c]) or pd.api.types.is_string_dtype(df_read[c]):
            mask = df_read[c].apply(lambda x: isinstance(x, str) and is_null_token(x))
            df_read.loc[mask, c] = np.nan

    pandas_null_count = int(df_read["val"].isna().sum())

    assert pandas_null_count == scan_null_count, (
        f"X-02-C FAIL: token={repr(null_token)}: scan null_count={scan_null_count}, "
        f"pandas (zedda tokens) null_count={pandas_null_count}."
    )


def test_x02d_whitespace_row_preserved_in_output(tmp_path: Path) -> None:
    """clean() must produce exactly 3 rows when input has 3 rows including whitespace val."""
    src = tmp_path / "x02d.csv"
    src.write_text("id,val\n1,A\n2, \n3,B\n", encoding="utf-8")

    profile = zd.scan(str(src))
    assert profile.num_rows == 3, f"scan row_count={profile.num_rows}, expected 3"

    out = tmp_path / "x02d_clean.csv"
    zd.clean(str(src), output=str(out), dry_run=False, approved=True)

    df_out = pd.read_csv(str(out), keep_default_na=False)
    assert len(df_out) == 3, (
        f"X-02-D FAIL: output has {len(df_out)} rows, expected 3."
    )


def test_x02e_score_after_matches_rescan(tmp_path: Path) -> None:
    """Score in audit trail must not contradict a fresh scan of the output file."""
    src = tmp_path / "x02e.csv"
    src.write_text("id,val\n1,A\n2,?\n3,B\n4,C\n", encoding="utf-8")

    out = tmp_path / "x02e_clean.csv"
    zd.clean(str(src), output=str(out), dry_run=False, approved=True)

    audit_candidates = list(tmp_path.glob("*.audit.json"))
    assert audit_candidates, "No audit JSON found"
    audit = json.loads(audit_candidates[0].read_text())
    audit_score_after = audit.get("score_after", -1)

    profile_out = zd.scan(str(out))
    from zedda._profile_print import _quality_score
    rescan_score = _quality_score(profile_out)

    assert abs(audit_score_after - rescan_score) <= 5, (
        f"X-02-E FAIL: audit score_after={audit_score_after}, rescan={rescan_score}. "
        f"Score contradicts reality."
    )
