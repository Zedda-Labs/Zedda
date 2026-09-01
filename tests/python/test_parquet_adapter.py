import pytest
import pandas as pd
import zedda as zd
from zedda._adapters.parquet_adapter import ParquetAdapter
from zedda._models import MetricStatus

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = None
    pq = None


@pytest.fixture
def parquet_file(tmp_path):
    if pa is None:
        pytest.skip("pyarrow not installed")

    df = pd.DataFrame(
        {
            "id": [1, 2, 3, None, 5],
            "val": [10.5, 20.0, 15.5, 12.0, 10.0],
            "category": ["A", "B", "A", "C", "B"],
        }
    )
    table = pa.Table.from_pandas(df)
    p = tmp_path / "test.parquet"
    # Write with small row group size to test row group handling
    pq.write_table(table, p, row_group_size=2)
    return str(p)


def test_parquet_adapter_coverage(parquet_file):
    adapter = ParquetAdapter(parquet_file)
    coverage = adapter.coverage()

    assert coverage.format == "parquet"
    assert coverage.row_count == 5
    assert coverage.column_count == 3
    assert coverage.metadata["row_group_count"] == 3
    assert coverage.metadata["footer_stats_available"] is True


def test_parquet_adapter_schema_and_footer_stats(parquet_file):
    adapter = ParquetAdapter(parquet_file)
    schema = adapter.schema()

    assert len(schema.columns) == 3

    # Check that footer stats were extracted correctly
    id_col = schema.get_column("id")
    assert "footer_metrics" in id_col.metadata

    metrics = id_col.metadata["footer_metrics"]
    assert "null_count" in metrics
    assert metrics["null_count"].value == 1
    assert metrics["null_count"].status == MetricStatus.EXACT
    assert metrics["null_count"].method == "parquet_footer"

    # Check val column min/max
    val_col = schema.get_column("val")
    val_metrics = val_col.metadata["footer_metrics"]
    assert val_metrics["min"].value == 10.0
    assert val_metrics["max"].value == 20.0


def test_parquet_adapter_sampled(parquet_file):
    # A sample_size is a strict row bound, including when the file has only a
    # few row groups.
    adapter = ParquetAdapter(parquet_file, is_sampled=True, sample_size=2)
    coverage = adapter.coverage()

    assert coverage.metadata["is_sampled"] is True
    assert coverage.metadata["rows_examined"] == 2
    assert coverage.coverage_fraction == pytest.approx(2 / 5)


def test_parquet_sample_size_is_bounded_for_many_row_groups(tmp_path):
    values = list(range(100))
    table = pa.table({"id": values, "duplicate": [value % 2 for value in values]})
    path = tmp_path / "many_groups.parquet"
    pq.write_table(table, path, row_group_size=10)

    adapter = ParquetAdapter(str(path), is_sampled=True, sample_size=15)
    coverage = adapter.coverage()

    assert coverage.metadata["rows_examined"] == 15
    assert coverage.coverage_fraction == pytest.approx(0.15)

    profile = zd.scan(str(path), sample_size=15)
    id_col = next(column for column in profile.columns if column.name == "id")
    duplicate_col = next(
        column for column in profile.columns if column.name == "duplicate"
    )
    assert id_col.unique_pct == pytest.approx(100.0)
    assert duplicate_col.unique_pct == pytest.approx(2 / 15 * 100)


def test_parquet_adapter_records_raises():
    if pa is None:
        pytest.skip("pyarrow not installed")
    adapter = ParquetAdapter("dummy.parquet")
    with pytest.raises(NotImplementedError, match="kernel-delegation"):
        list(adapter.records())
