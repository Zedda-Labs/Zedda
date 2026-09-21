import pytest
from pathlib import Path
import zedda as zd
import pandas as pd


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_fix_mostly_null(fixtures_dir):
    # Just checking fix code generation
    p = zd.scan(str(fixtures_dir / "mostly_null.csv"))
    from zedda._fix import generate_fix_code

    fixes = generate_fix_code(p)
    assert len(fixes["all_code"]) > 0
    # The high nulls should suggest dropping
    assert any("drop(columns=" in code for code in fixes["all_code"])


def test_fix_all_good():
    df = pd.DataFrame(
        {
            "clean_num": [10.5, 11.2, 12.1, 10.8, 11.5, 12.0],
        }
    )
    p = zd.scan(df)
    from zedda._fix import generate_fix_code

    fixes = generate_fix_code(p)
    assert fixes["n_issues"] == 0


def test_fix_apply():
    # Test apply=True on DataFrame
    df = pd.DataFrame(
        {"bad_col": [None, None, None, None, 5], "good_col": [1, 1, 2, 2, 2]}
    )
    fixed_df = zd.fix(df, apply=True)
    # The fix should drop the mostly null column
    assert "bad_col" not in fixed_df.columns
    assert "good_col" in fixed_df.columns


def test_fix_impute():
    df = pd.DataFrame(
        {"impute_col": [1.0, 2.0, None, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]}
    )
    fixed_df = zd.fix(df, apply=True)
    # The fix should impute the missing value
    assert fixed_df["impute_col"].isnull().sum() == 0


def test_fix_cli_api(fixtures_dir):
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        zd.fix(str(fixtures_dir / "mostly_null.csv"))
    out = f.getvalue()
    assert "df = df.drop(columns=" in out
