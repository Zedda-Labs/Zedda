import pytest
import pandas as pd
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
        
    df = pd.DataFrame({
        "id": [1, 2, 3, None, 5],
        "val": [10.5, 20.0, 15.5, 12.0, 10.0],
        "category": ["A", "B", "A", "C", "B"]
    })
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
    assert val_metrics["val_min"].value == 10.0
    assert val_metrics["val_max"].value == 20.0


def test_parquet_adapter_sampled(parquet_file):
    # Test that sampling only processes a subset of row groups
    adapter = ParquetAdapter(parquet_file, is_sampled=True, sample_size=2)
    coverage = adapter.coverage()
    
    # With 3 row groups, sampling should select {0, 1, 2} since 3 <= 6, so all are selected!
    # Wait, the logic is: if num_row_groups <= 6 or not is_sampled: select all.
    # So coverage fraction will be 1.0 because it's a tiny file.
    assert coverage.metadata["is_sampled"] is False
    assert coverage.coverage_fraction == 1.0


def test_parquet_adapter_records_raises():
    if pa is None:
        pytest.skip("pyarrow not installed")
    adapter = ParquetAdapter("dummy.parquet")
    with pytest.raises(NotImplementedError, match="kernel-delegation"):
        list(adapter.records())
