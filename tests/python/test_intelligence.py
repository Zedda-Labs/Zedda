import numpy as np
import pandas as pd
import zedda as zd
from zedda.__init__ import _quality_score


def test_clean_score_dropped_columns(tmp_path):
    """
    Test that dropping a column entirely should not automatically
    push score to 100 unless genuinely all remaining issues are resolved,
    and dropping columns applies a penalty.
    """
    f = tmp_path / "bad.csv"
    df = pd.DataFrame(
        {
            "good_col": [1, 2, 1, 2, 1],  # not unique, so it won't be dropped as ID
            "bad_id": [1, 2, 3, 4, 5],  # 100% unique ID
            "bad_nulls": [np.nan, np.nan, np.nan, np.nan, 5],  # 80% nulls -> dropped
        }
    )
    df.to_csv(f, index=False)

    p = zd.scan(str(f))
    _quality_score(p)

    # Clean it
    out_f = tmp_path / "clean.csv"
    zd.clean(str(f), output=str(out_f))

    # It dropped bad_id and bad_nulls, remaining is good_col.
    # original_cols was 3, new is 1. Dropped 2 cols.
    # Penalty should be 2 * 5 = 10. Max score should be 90.

    p_after = zd.scan(str(out_f))
    score_after = _quality_score(p_after, original_cols=3)

    # 100 base - 10 (dropped columns penalty) = 90
    assert score_after == 90
    # ensure it's not 100 artificially
    assert score_after < 100


def test_merge_skip_id_binary_dist_check(tmp_path, capsys):
    """
    Test that PassengerId and Survived should NEVER appear in
    Distribution Check output, regardless of how different the files are.
    """
    f1 = tmp_path / "f1.csv"
    f2 = tmp_path / "f2.csv"

    # f1 has ID 1-10, survived all 0
    df1 = pd.DataFrame(
        {
            "PassengerId": list(range(1, 11)),
            "Survived": [0] * 10,
            "NormalNum": [
                10,
                10,
                10,
                10,
                11,
                11,
                11,
                12,
                12,
                12,
            ],  # 3 unique, 10 rows -> 30% unique
        }
    )
    df1.to_csv(f1, index=False)

    # f2 has ID 101-110 (huge mean shift), survived all 1 (huge mean shift)
    df2 = pd.DataFrame(
        {
            "PassengerId": list(range(101, 111)),
            "Survived": [1] * 10,
            "NormalNum": [50, 50, 50, 50, 51, 51, 51, 52, 52, 52],  # Real shift
        }
    )
    df2.to_csv(f2, index=False)

    out_f = tmp_path / "merged.csv"
    zd.merge([str(f1), str(f2)], output=str(out_f))

    captured = capsys.readouterr()
    output = captured.out

    # The normal number should trigger a distribution warning
    assert "NormalNum" in output
    assert "above" in output

    # ID and Binary shouldn't be warned about distribution shifts
    assert "'PassengerId' —" not in output
    assert "'Survived' —" not in output


def test_warnings_format(tmp_path, capsys):
    f = tmp_path / "warn.csv"
    df = pd.DataFrame({"ID": range(1, 6), "Missing": [1, None, None, 4, 5]})
    df.to_csv(f, index=False)

    zd.warnings(str(f))
    captured = capsys.readouterr()
    output = captured.out

    # Should contain warnings header and specific column warnings
    assert "Found" in output
    assert "issues" in output
    assert "ID" in output
    assert "100% unique" in output
    assert "Missing" in output


def test_fix_apply_true(tmp_path):
    f = tmp_path / "fix.csv"
    df = pd.DataFrame({"ID": range(1, 6), "MissingStr": ["a", None, None, None, "b"]})
    df.to_csv(f, index=False)

    # Test apply=True returns cleaned DataFrame directly
    clean_df = zd.fix(str(f), apply=True)

    assert isinstance(clean_df, pd.DataFrame)
    # ID should be dropped
    assert "ID" not in clean_df.columns
    # MissingStr should be dropped because >50% nulls
    assert "MissingStr" not in clean_df.columns
    assert len(clean_df.columns) == 0
