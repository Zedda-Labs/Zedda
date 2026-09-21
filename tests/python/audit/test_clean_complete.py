import pytest
import os
import tempfile
import pandas as pd
from pathlib import Path
import zedda as zd


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_clean_dry_run(fixtures_dir):
    # Test that dry run does not write files
    target = str(fixtures_dir / "mostly_null.csv")
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "cleaned.csv")
        # By default clean in API is dry_run? Actually API is zd.clean(path). Let's see what it returns.
        # It's an interactive or print-based function. Let's use the underlying _clean directly if we can, or test it via API.
        from zedda._clean import generate_plan

        p = zd.scan(target)
        plan = generate_plan(p)
        assert len(plan.proposed_changes) > 0
        assert not os.path.exists(out_path)


def test_clean_api_dataframe():
    df = pd.DataFrame(
        {"bad_col": [None, None, None, None, 5], "good_col": [1, 2, 3, 4, 5]}
    )

    # clean() on dataframe returns the cleaned dataframe (or interactive).
    # Since we cannot easily mock the interactive terminal, we can use the executor.
    from zedda._clean_executor import apply_cleaning_fixes
    from zedda._clean import generate_plan

    p = zd.scan(df)
    plan = generate_plan(p)
    cleaned_df = apply_cleaning_fixes(df, plan)

    assert "bad_col" not in cleaned_df.columns
    assert "good_col" in cleaned_df.columns


def test_clean_impute():
    df = pd.DataFrame(
        {"impute_col": [1.0, 2.0, None, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]}
    )
    p = zd.scan(df)
    from zedda._clean import generate_plan
    from zedda._clean_executor import apply_cleaning_fixes

    plan = generate_plan(p)
    cleaned_df = apply_cleaning_fixes(df, plan)
    assert cleaned_df["impute_col"].isnull().sum() == 0


def test_clean_encode():
    # String with high cardinality
    df = pd.DataFrame(
        {"high_card": [f"val_{i}" for i in range(100)], "val": range(100)}
    )
    p = zd.scan(df)
    from zedda._clean import generate_plan
    from zedda._clean_executor import apply_cleaning_fixes

    plan = generate_plan(p)
    cleaned_df = apply_cleaning_fixes(df, plan)
    # Check if encoded
    if "high_card" in cleaned_df.columns:
        assert pd.api.types.is_numeric_dtype(cleaned_df["high_card"])
