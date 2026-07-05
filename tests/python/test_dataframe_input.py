import io
import os
import sys

import pandas as pd
import polars as pl
import pytest
import zedda as zd


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "A": [1, 2, 3, 4, 5],
            "B": ["a", "b", "c", "d", "e"],
            "C": [1.1, 2.2, 3.3, 4.4, 5.5],
        }
    )


@pytest.fixture
def sample_pl_df():
    return pl.DataFrame(
        {
            "A": [1, 2, 3, 4, 5],
            "B": ["a", "b", "c", "d", "e"],
            "C": [1.1, 2.2, 3.3, 4.4, 5.5],
        }
    )


def test_scan_pandas_df(sample_df):
    p = zd.scan(sample_df)
    assert p.num_rows == 5
    assert p.num_cols == 3
    assert p.columns[0].name == "A"


def test_scan_polars_df(sample_pl_df):
    p = zd.scan(sample_pl_df)
    assert p.num_rows == 5
    assert p.num_cols == 3


def test_profile_pandas_df(sample_df):
    # Should not raise any errors and output successfully
    p = zd.profile(sample_df)
    assert p.num_rows == 5


def test_compare_df(sample_df):
    df2 = sample_df.copy()
    df2.loc[0, "A"] = 100
    # Capture output to prevent spamming test log, but just ensure it doesn't crash
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        zd.compare(sample_df, df2)
        zd.warnings(sample_df)
        zd.ml_ready(sample_df)
        zd.fix(sample_df)
    finally:
        sys.stdout = old_stdout


def test_unsupported_input():
    with pytest.raises(zd.ZeddaError, match="Unsupported input type"):
        zd.scan([1, 2, 3])


def test_temp_file_cleanup(sample_df, monkeypatch):
    original_unlink = os.unlink
    unlinked_files = []

    def mock_unlink(path):
        unlinked_files.append(path)
        original_unlink(path)

    monkeypatch.setattr(os, "unlink", mock_unlink)
    p = zd.scan(sample_df)

    assert len(unlinked_files) == 1
    assert unlinked_files[0].endswith(".parquet")
    assert not os.path.exists(unlinked_files[0])
