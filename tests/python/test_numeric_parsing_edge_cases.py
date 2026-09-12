"""Tests for numeric parsing edge cases and boundaries in ProfileBuilder."""

import zedda as zd


def _get_col(profile, name):
    return next(c for c in profile.columns if c.name == name)


def test_numeric_parsing_integers_and_signs(tmp_path):
    csv_file = tmp_path / "test_ints.csv"
    csv_file.write_text(
        "id,val,flag,leading_zero,neg\n"
        "1,123,0,007,-42\n"
        "2,+456,1,000,-100\n"
        "3,-789,0,0123,+0\n"
        "4,0,1,00000,-0\n",
        encoding="utf-8",
    )

    profile = zd.scan(str(csv_file))
    assert profile.num_rows == 4
    assert profile.num_cols == 5

    val_col = _get_col(profile, "val")
    assert val_col.type in ("int", "integer", "float")
    assert val_col.null_count == 0

    flag_col = _get_col(profile, "flag")
    assert flag_col.null_count == 0

    zero_col = _get_col(profile, "leading_zero")
    assert zero_col.null_count == 0

    neg_col = _get_col(profile, "neg")
    assert neg_col.null_count == 0


def test_numeric_parsing_15_digit_boundary(tmp_path):
    csv_file = tmp_path / "test_15_digits.csv"
    csv_file.write_text(
        "big_int,big_neg\n"
        "999999999999999,-999999999999999\n"
        "100000000000000,-100000000000000\n",
        encoding="utf-8",
    )

    profile = zd.scan(str(csv_file))
    assert profile.num_rows == 2
    assert profile.num_cols == 2

    c1 = _get_col(profile, "big_int")
    c2 = _get_col(profile, "big_neg")
    assert c1.null_count == 0
    assert c2.null_count == 0
    assert c1.val_min == 100000000000000.0
    assert c1.val_max == 999999999999999.0
    assert c2.val_min == -999999999999999.0
    assert c2.val_max == -100000000000000.0


def test_numeric_parsing_floats_and_scientific(tmp_path):
    csv_file = tmp_path / "test_floats.csv"
    csv_file.write_text(
        "f1,f2,sci\n123.456,-123.456,1e3\n0.0,-0.0,-1e-3\n1.5e2,-1.5e-2,1.23e4\n",
        encoding="utf-8",
    )

    profile = zd.scan(str(csv_file))
    assert profile.num_rows == 3
    assert profile.num_cols == 3

    f1 = _get_col(profile, "f1")
    assert f1.null_count == 0
    sci = _get_col(profile, "sci")
    assert sci.null_count == 0


def test_numeric_parsing_mismatches_and_nulls(tmp_path):
    csv_file = tmp_path / "test_mismatch.csv"
    # Column is mostly numeric so typed as integer/float, with one malformed string
    csv_file.write_text(
        "mostly_num,with_nulls\n10,1.5\n20,NaN\n30,null\n40,2.5\n50,\n60,none\n",
        encoding="utf-8",
    )

    profile = zd.scan(str(csv_file))
    assert profile.num_rows == 6
    c_nulls = _get_col(profile, "with_nulls")
    assert c_nulls.null_count == 4  # NaN, null, empty, none
