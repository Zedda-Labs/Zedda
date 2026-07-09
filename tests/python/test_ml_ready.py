import pytest
import pandas as pd
import zedda as zd

def test_ml_ready_basic():
    df = pd.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "val": [10, 20, 30, 40, 50],
        "cat": ["A", "B", "A", "B", "A"]
    })
    result = zd.ml_ready(df)
    assert result is None  # Since it returns None

def test_ml_ready_type_coercion():
    df = pd.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "val": ["10", "20", "30a", "40", "50"],
    })
    # Should not crash on type coercion (Task 2 fix)
    zd.ml_ready(df)
