import pytest
import pandas as pd
import zedda as zd

def test_compare_csv(tmp_path):
    df1 = pd.DataFrame({"id": [1, 2], "val": [10.0, 20.0]})
    df2 = pd.DataFrame({"id": [1, 2], "val": [10.0, 30.0]})
    p1 = tmp_path / "1.csv"
    p2 = tmp_path / "2.csv"
    df1.to_csv(p1, index=False)
    df2.to_csv(p2, index=False)

    zd.compare(str(p1), str(p2))

def test_compare_dataframe():
    df1 = pd.DataFrame({"id": [1, 2], "val": [10.0, 20.0]})
    df2 = pd.DataFrame({"id": [1, 2], "val": [10.0, 30.0]})
    zd.compare(df1, df2)
