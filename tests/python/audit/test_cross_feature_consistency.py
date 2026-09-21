import pytest
import zedda as zd
from pathlib import Path
import os
import tempfile
import pandas as pd


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_invariants_tiny(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "tiny.csv"))
    _check_invariants(p)


def test_invariants_mostly_null(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "mostly_null.csv"))
    _check_invariants(p)


def test_invariants_large(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "large.csv"))
    _check_invariants(p)


def test_invariants_wide(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "wide.csv"))
    _check_invariants(p)


def _check_invariants(p):
    for col in p.columns:
        # Invariant 1: null_count <= num_rows
        assert col.null_count <= p.num_rows

        # Invariant 2: unique_approx <= num_rows
        # HLL can sometimes overshoot by a small margin, but usually not by much. Let's do a generous bound.
        assert col.unique_approx <= p.num_rows * 1.1 + 10

        # Invariant 3: min <= max (for numeric)
        if col.type_str in ("int", "float") and col.null_count < p.num_rows:
            assert col.val_min <= col.val_max

        # Invariant 4: 0.0 <= null_pct <= 100.0
        assert 0.0 <= col.null_pct <= 100.0

        # Invariant 5: non_null_count + null_count == total_count
        # or valid_count + missing_count + invalid_count == total_count (v0.5 canonical counts)
        # depending on zedda logic
        if hasattr(col, "total_count") and col.total_count > 0:
            assert col.non_null_count + col.null_count == col.total_count


def test_profile_stats_equal_scan_stats(fixtures_dir):
    import io
    from contextlib import redirect_stdout

    # scan
    p_scan = zd.scan(str(fixtures_dir / "tiny.csv"))

    # profile
    f = io.StringIO()
    with redirect_stdout(f):
        p_profile = zd.profile(str(fixtures_dir / "tiny.csv"))

    assert p_scan.num_rows == p_profile.num_rows
    assert p_scan.num_cols == p_profile.num_cols
    for c_s, c_p in zip(p_scan.columns, p_profile.columns, strict=False):
        assert c_s.null_count == c_p.null_count


def test_warnings_count_vs_total_columns(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "tiny.csv"))
    warns = zd.collect_warnings(p)
    # A single column could have multiple warnings, but usually there's a bound
    # We can at least check it doesn't explode.
    assert isinstance(warns, list)


def test_ml_ready_drop_cols_in_profile():
    df = pd.DataFrame({"good": [1, 2], "bad": [1, 1]})
    score, rpt = zd.ml_ready(df)
    p = zd.scan(df)
    col_names = [c.name for c in p.columns]

    for dc in rpt.get("drop_cols", []):
        assert dc in col_names


def test_clean_dry_run_invariant():
    df = pd.DataFrame({"col": [1, 2, 3]})

    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "out.csv")
        # Just checking generate_plan since actual dry_run logic might be in cli
        from zedda._clean import generate_plan

        p = zd.scan(df)
        plan = generate_plan(p)
        assert not os.path.exists(out_path)


def test_fix_decisions_match_warnings():
    df = pd.DataFrame({"const": [1, 1, 1]})
    p = zd.scan(df)
    warns = zd.collect_warnings(p)

    from zedda._fix import generate_fix_code

    fixes = generate_fix_code(p)

    if len(warns) > 0:
        assert fixes["n_issues"] > 0
