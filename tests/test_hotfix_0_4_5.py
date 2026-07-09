import sys
from pathlib import Path

import pandas as pd
import pytest

import zedda as zd


def test_bug_1_pandas_dataframe_input(tmp_path):
    """
    Test that a pandas DataFrame loaded from a real CSV file is successfully
    processed by zd.scan() and zd.profile() without raising ZeddaError.
    """
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("A,B,C\n1,2,3\n4,5,6")
    
    df = pd.read_csv(str(csv_file))
    
    # scan() should succeed and return a DatasetProfile
    p = zd.scan(df)
    assert p.num_rows == 2
    assert p.num_cols == 3
    
    # profile() should succeed without error
    try:
        zd.profile(df)
    except Exception as e:
        pytest.fail(f"zd.profile(df) raised an unexpected exception: {e}")


def test_bug_2_clean_numeric_garbage_coercion(tmp_path):
    """
    Test that zd.clean() correctly coerces garbage string values to NaN
    in otherwise numeric columns, rather than crashing with TypeError.
    """
    csv_file = tmp_path / "garbage.csv"
    # Column A is numeric, but has "4a"
    # Column B is pure numeric
    csv_file.write_text("A,B\n1,10\n1,10\n3,30\n4a,30\n5,10\n,10")
    
    output_file = tmp_path / "garbage_clean.csv"
    
    # Should not crash!
    try:
        df_clean = zd.clean(str(csv_file), output=str(output_file))
    except Exception as e:
        pytest.fail(f"zd.clean() crashed on numeric garbage: {e}")
        
    # The '4a' should be coerced to NaN and then imputed with median.
    # Original valid values: 1, 2, 3, 5 -> median is 2.5
    assert output_file.exists()
    df_result = pd.read_csv(str(output_file))
    
    # Check that there are no NaNs left
    assert df_result["A"].isnull().sum() == 0
    
    # The 4th row (index 3) should have been imputed (because of 4a)
    imputed_value = df_result["A"].iloc[3]
    # Median of [1, 1, 3, 5] is 2.0
    assert float(imputed_value) == 2.0
