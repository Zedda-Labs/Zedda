"""
Parquet profiling tests — exercises zd.profile() on Parquet files.

Converted from standalone script to proper pytest format so that
`pytest tests/python/test_parquet.py -v` collects and runs these tests.
(BUG-03 fix)
"""

import pytest
import zedda as zd

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")


def test_parquet_profile(tmp_path):
    """Test that zd.profile() correctly profiles a Parquet file."""
    table = pa.table(
        {
            "a": [1, 2, 3, 4, None],
            "b": ["apple", "banana", "apple", None, "orange"],
            "c": [10.5, 20.2, None, 40.5, 50.1],
        }
    )
    path = tmp_path / "test.parquet"
    pq.write_table(table, str(path))

    p = zd.profile(str(path))
    assert p.num_rows == 5
    assert p.num_cols == 3


def test_parquet_column_types(tmp_path):
    """Test that Parquet profiling detects column types correctly."""
    table = pa.table(
        {
            "int_col": [1, 2, 3, 4, 5],
            "float_col": [1.1, 2.2, 3.3, 4.4, 5.5],
            "str_col": ["a", "b", "c", "d", "e"],
        }
    )
    path = tmp_path / "types.parquet"
    pq.write_table(table, str(path))

    p = zd.profile(str(path))
    assert p.num_rows == 5
    assert p.num_cols == 3

    col_names = [c.name for c in p.columns]
    assert "int_col" in col_names
    assert "float_col" in col_names
    assert "str_col" in col_names


def test_parquet_nulls(tmp_path):
    """Test that Parquet profiling correctly counts nulls."""
    table = pa.table(
        {
            "a": [1, None, None, 4, 5],
            "b": ["x", "y", None, None, None],
        }
    )
    path = tmp_path / "nulls.parquet"
    pq.write_table(table, str(path))

    p = zd.profile(str(path))
    assert p.num_rows == 5
    assert p.num_cols == 2

    a_col = next((c for c in p.columns if c.name == "a"), None)
    b_col = next((c for c in p.columns if c.name == "b"), None)
    assert a_col is not None
    assert b_col is not None
    assert a_col.null_count == 2
    assert b_col.null_count == 3
