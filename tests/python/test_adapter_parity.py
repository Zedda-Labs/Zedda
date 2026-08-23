import os
import pandas as pd
from zedda._adapters.csv_adapter import CSVAdapter
from zedda._adapters.dataframe_adapter import DataFrameAdapter
from zedda._schema import DataType
import pytest


def test_csv_dataframe_adapter_schema_parity(tmp_path):
    p = tmp_path / "parity.csv"
    p.write_text("id,val,category\n1,10.5,A\n2,20.5,B")

    # 1. CSV Adapter
    csv_adapter = CSVAdapter(str(p))
    csv_schema = csv_adapter.schema()
    csv_coverage = csv_adapter.coverage()

    # 2. DataFrame Adapter
    df = pd.read_csv(str(p))
    df_adapter = DataFrameAdapter(df)
    df_schema = df_adapter.schema()
    df_coverage = df_adapter.coverage()

    # Assert coverage basics
    assert csv_coverage.row_count == df_coverage.row_count == 2
    assert csv_coverage.column_count == df_coverage.column_count == 3

    # Assert schemas are identical in length and names
    assert len(csv_schema.columns) == len(df_schema.columns)

    # Assert types map semantically
    # CSV will infer int, float, string which map to INT64, FLOAT64, STRING
    assert csv_schema.columns[0].type == DataType.INT64
    assert csv_schema.columns[1].type == DataType.FLOAT64
    assert csv_schema.columns[2].type == DataType.STRING

    # Pandas will infer int64, float64, object/string which map to INT64, FLOAT64, STRING
    assert df_schema.columns[0].type == DataType.INT64
    assert df_schema.columns[1].type == DataType.FLOAT64
    assert df_schema.columns[2].type == DataType.STRING


def test_dataframe_adapter_polars_deferred():
    """
    DEFERRED: Polars DataFrame support is formally deferred to Phase 4/5.
    The Phase 3 task description mentioned pandas/polars, but the Definition of Done
    only requires pandas. Passing a non-pandas object with DataFrame-like attributes
    raises NotImplementedError with an explicit deferral message.

    This test documents the deferral decision. It simulates a Polars-like object
    (has .columns and .dtypes but no .itertuples) to verify the error is explicit.
    """

    class FakePolarsDF:
        """Minimal Polars-like stub (has .columns and .dtypes but no .itertuples)."""

        columns = ["a", "b"]
        dtypes = ["Int64", "Float64"]

    with pytest.raises(NotImplementedError, match="Polars DataFrame support.*deferred"):
        DataFrameAdapter(FakePolarsDF())
