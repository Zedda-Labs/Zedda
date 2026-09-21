import pytest
import pandas as pd
import zedda as zd
from zedda._errors import ZeddaError


def test_merge_identical_schemas():
    df1 = pd.DataFrame({"id": [1, 2], "val": ["a", "b"]})
    df2 = pd.DataFrame({"id": [3, 4], "val": ["c", "d"]})

    # merge() can take dataframes or paths
    merged = zd.merge([df1, df2])
    assert len(merged) == 4
    assert list(merged.columns) == ["id", "val"]


def test_merge_dedup():
    df1 = pd.DataFrame({"id": [1, 2], "val": ["a", "b"]})
    df2 = pd.DataFrame({"id": [2, 3], "val": ["b", "c"]})

    merged = zd.merge([df1, df2], dedup=True)
    assert len(merged) == 3


def test_merge_schema_mismatch():
    df1 = pd.DataFrame({"id": [1, 2], "val1": ["a", "b"]})
    df2 = pd.DataFrame({"id": [3, 4], "val2": ["c", "d"]})

    # Depending on implementation, it might raise or concatenate with NaNs
    try:
        merged = zd.merge([df1, df2], strict=True)
        # If strict is True, it should raise
        raise AssertionError("Should have raised an error on strict merge")
    except (ZeddaError, ValueError):
        pass


def test_merge_source_tracking():
    df1 = pd.DataFrame({"id": [1]})
    df2 = pd.DataFrame({"id": [2]})

    merged = zd.merge([df1, df2], track_source=True)
    assert "_source" in merged.columns
    assert merged["_source"].tolist() == ["df_0", "df_1"]
