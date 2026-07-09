import pytest
import pandas as pd
import zedda as zd

def test_warnings_basic():
    df = pd.DataFrame({"id": [1, 2, 3, 4], "val": [1, None, 3, 4]})
    zd.warnings(df)
