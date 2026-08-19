import os
import io
import json
import pytest
from unittest.mock import patch
from contextlib import redirect_stdout
import zedda as zd


def get_output(func, *args, **kwargs):
    f = io.StringIO()
    with redirect_stdout(f):
        func(*args, **kwargs)
    return f.getvalue()


def test_warnings_hides_fix_code_by_default():
    path = "tests/data/titanic.csv"
    out = get_output(zd.warnings, path)
    assert "→ Fix:" not in out
    assert "df[" not in out
    assert "Copy-Paste Fix Block:" not in out


def test_warnings_show_fixes_true_reveals_code():
    path = "tests/data/titanic.csv"
    out = get_output(zd.warnings, path, show_fixes=True)
    assert "→ Fix:" in out
    assert "Copy-Paste Fix Block:" in out


def test_clean_audit_filename_is_dot_audit_json(tmp_path):
    path = "tests/data/titanic.csv"
    out_file = tmp_path / "cleaned.csv"
    out = get_output(zd.clean, path, output=str(out_file))

    audit_file = tmp_path / "cleaned.audit.json"
    assert audit_file.exists()
    assert "cleaned.audit.json" in out
    assert not (tmp_path / "cleaned.csv.audit.json").exists()


def test_ml_ready_action_column_has_no_literal_code():
    path = "tests/data/titanic.csv"
    out = get_output(zd.ml_ready, path)

    # We should see plain English words like "Impute median", "DROP", "KEEP as-is"
    assert "Impute" in out or "DROP" in out or "KEEP as-is" in out
    # We should NOT see raw code
    assert "df[" not in out
    assert "fillna(" not in out


def test_score_bar_uses_block_characters_only():
    path = "tests/data/titanic.csv"
    prof_out = get_output(zd.profile, path)
    ml_out = get_output(zd.ml_ready, path)

    # Check for block characters
    assert "█" in prof_out
    assert "░" in prof_out
    assert "█" in ml_out
    assert "░" in ml_out

    # Ensure no dashboard dashes
    # Just to be safe, check that the specific bad string '========--' is not there
    assert "========--" not in prof_out
    assert "========--" not in ml_out


def test_profile_scan_ask_agree_on_null_percentages():
    path = "tests/data/titanic.csv"

    prof_out = get_output(zd.profile, path)
    prof_lines = [
        line for line in prof_out.split("\\n") if "Age" in line and "19.9%" in line
    ]
    assert len(prof_lines) == 1, "profile() should show 19.9% for Age"

    p = zd.scan(path)
    age_col = next(c for c in p.columns if c.name == "Age")
    # approx 19.865%
    assert round(age_col.null_pct, 1) == 19.9, "scan() should be 19.9% (rounded)"

    ask_out = get_output(
        zd.ask,
        path,
        "which columns have missing values and what are their null percentages? Use exact numbers.",
    )
    assert "19.9%" in ask_out, "ask() should state 19.9% for Age"
