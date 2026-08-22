import pytest
import os
import pandas as pd
from zedda._adapters.registry import AdapterRegistry
from zedda._adapters.csv_adapter import CSVAdapter
from zedda._adapters.dataframe_adapter import DataFrameAdapter
from zedda._schema import DataType, LogicalRecord
from zedda._errors import ZeddaError

def test_registry_resolves_csv(tmp_path):
    p = tmp_path / "test.csv"
    p.write_text("a,b\n1,2")
    
    adapter = AdapterRegistry.resolve(str(p))
    assert isinstance(adapter, CSVAdapter)
    
def test_dataframe_adapter_records_delegates():
    df = pd.DataFrame({"a": [1, 2]})
    adapter = AdapterRegistry.resolve(df)
    with pytest.raises(NotImplementedError, match="pattern"):
        list(adapter.records())

def test_registry_raises_on_unknown(tmp_path):
    p = tmp_path / "test.unknown_ext"
    p.write_text("hello")
    
    with pytest.raises(ZeddaError, match="Unsupported file format"):
        AdapterRegistry.resolve(str(p))

def test_csv_adapter_schema(tmp_path):
    p = tmp_path / "test.csv"
    p.write_text("a,b\n1,foo\n2,bar")
    
    adapter = CSVAdapter(str(p))
    schema = adapter.schema()
    
    assert len(schema.columns) == 2
    assert schema.columns[0].name == "a"
    assert schema.columns[1].name == "b"

def test_dataframe_adapter_schema():
    df = pd.DataFrame({
        "a": pd.Series([1, 2], dtype="int32"),
        "b": pd.Series([1.5, 2.5], dtype="float64"),
        "c": pd.Series(["x", "y"], dtype="object")
    })
    
    adapter = DataFrameAdapter(df)
    schema = adapter.schema()
    
    assert len(schema.columns) == 3
    assert schema.columns[0].name == "a"
    assert schema.columns[0].type == DataType.INT64
    assert schema.columns[1].name == "b"
    assert schema.columns[1].type == DataType.FLOAT64
    assert schema.columns[2].name == "c"
    assert schema.columns[2].type == DataType.STRING


# ── Kernel-delegation contract tests ─────────────────────────────────────────

def test_csv_adapter_records_raises_not_implemented(tmp_path):
    """
    CSVAdapter uses the C++-kernel-delegation pattern.
    records() MUST raise NotImplementedError — this is the documented contract.
    Callers must use schema() and coverage() instead.
    """
    p = tmp_path / "test.csv"
    p.write_text("a,b\n1,2\n3,4")
    adapter = CSVAdapter(str(p))
    with pytest.raises(NotImplementedError, match="CSVAdapter delegates profiling to the C\\+\\+ kernel"):
        list(adapter.records())


def test_csv_adapter_kernel_delegation_provides_schema_and_coverage(tmp_path):
    """
    Even though records() is not available, the kernel-delegation contract
    requires schema() and coverage() to be fully populated after open().
    """
    p = tmp_path / "test.csv"
    p.write_text("id,score\n1,9.5\n2,8.0")
    adapter = CSVAdapter(str(p))
    schema = adapter.schema()
    coverage = adapter.coverage()

    assert len(schema.columns) == 2
    assert coverage.row_count == 2
    assert coverage.column_count == 2
    assert coverage.coverage_fraction == 1.0


def test_dataframe_adapter_records_delegates():
    df = pd.DataFrame({"x": [10, 20], "y": ["a", "b"]})
    adapter = DataFrameAdapter(df)
    with pytest.raises(NotImplementedError, match="pattern"):
        list(adapter.records())

