import pytest
import pandas as pd
import zedda as zd


def test_merge_basic(tmp_path):
    df1 = pd.DataFrame({"id": [1, 2], "v1": [10, 20]})
    df2 = pd.DataFrame({"id": [1, 2], "v2": [100, 200]})

    p1 = tmp_path / "1.csv"
    p2 = tmp_path / "2.csv"
    df1.to_csv(p1, index=False)
    df2.to_csv(p2, index=False)

    merged = zd.merge([str(p1), str(p2)])
    assert "v1" in merged.columns
    assert "v2" in merged.columns
    assert len(merged) == 4


def test_merge_dataframes():
    df1 = pd.DataFrame({"id": [1, 2], "v1": [10, 20]})
    df2 = pd.DataFrame({"id": [1, 2], "v2": [100, 200]})

    merged = zd.merge([df1, df2])
    assert "v1" in merged.columns
    assert "v2" in merged.columns
    assert len(merged) == 4
