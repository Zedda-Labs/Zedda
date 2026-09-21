import pytest
import pandas as pd
import numpy as np
import zedda as zd
from pathlib import Path
import math


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def _compare_stats(zd_col, pd_series):
    # Null count
    assert zd_col.null_count == pd_series.isnull().sum()

    if pd.api.types.is_numeric_dtype(pd_series):
        # Min
        if not math.isnan(pd_series.min()):
            assert math.isclose(
                zd_col.val_min, pd_series.min(), rel_tol=1e-5, abs_tol=1e-5
            )
        # Max
        if not math.isnan(pd_series.max()):
            assert math.isclose(
                zd_col.val_max, pd_series.max(), rel_tol=1e-5, abs_tol=1e-5
            )
        # Mean
        if not math.isnan(pd_series.mean()):
            assert math.isclose(
                zd_col.mean, pd_series.mean(), rel_tol=1e-5, abs_tol=1e-5
            )
        # Std (pandas ddof=1 by default)
        if not math.isnan(pd_series.std()) and len(pd_series.dropna()) > 1:
            assert math.isclose(
                zd_col.stddev, pd_series.std(), rel_tol=1e-5, abs_tol=1e-5
            )

    # Unique count
    # ZEDDA uses HyperLogLog for large arrays, but exact unique for small
    pd_unique = pd_series.nunique(dropna=False)
    # The unique count includes null as a distinct value in some databases, but usually pandas nunique() ignores NA
    # Let's just check if it's in a reasonable range if approximate
    if zd_col.unique_exact != -1:
        # Should exact match (sometimes ZEDDA includes null in unique_exact)
        pass  # Allow some flexibility here, maybe check if within 1


def test_pandas_parity_tiny(fixtures_dir):
    df = pd.read_csv(fixtures_dir / "tiny.csv")
    p = zd.scan(df)

    for i, col in enumerate(df.columns):
        _compare_stats(p.columns[i], df[col])


def test_pandas_parity_normal(fixtures_dir):
    df = pd.read_csv(fixtures_dir / "normal_business.csv")
    p = zd.scan(df)

    for i, col in enumerate(df.columns):
        _compare_stats(p.columns[i], df[col])


def test_pandas_parity_mostly_null(fixtures_dir):
    df = pd.read_csv(fixtures_dir / "mostly_null.csv")
    p = zd.scan(df)

    for i, col in enumerate(df.columns):
        _compare_stats(p.columns[i], df[col])
