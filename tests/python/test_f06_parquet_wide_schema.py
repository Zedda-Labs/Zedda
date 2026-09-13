import os
import pytest
import pyarrow as pa
import pyarrow.parquet as pq
import zedda


def test_parquet_wide_schema_heap_safety(tmp_path):
    """
    Regression test for C-4/BN-2: Parquet schema buffer heap overflow.
    Ensures that ParquetAdapter correctly handles wide schemas (150+ columns)
    with long type strings that would overflow a fixed 1024-byte buffer.
    """
    file_path = tmp_path / "wide_schema.parquet"

    # Create 250 columns with long names to inflate schema size
    fields = []
    for i in range(250):
        long_name = f"very_long_column_name_that_takes_up_space_in_schema_{i}"
        fields.append(pa.field(long_name, pa.int64()))

    schema = pa.schema(fields)

    # Write one row of dummy data
    data = [[i] for i in range(250)]
    table = pa.Table.from_arrays(data, schema=schema)
    pq.write_table(table, file_path)

    # Ensure scan succeeds without segfault or buffer overflow
    prof = zedda.scan(str(file_path))

    assert prof.num_cols == 250
    assert (
        prof.columns[0].name == "very_long_column_name_that_takes_up_space_in_schema_0"
    )
    assert (
        prof.columns[-1].name
        == "very_long_column_name_that_takes_up_space_in_schema_249"
    )
    assert prof.columns[0].metrics["min"].value == 0
