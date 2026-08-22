import pytest
import os
import pandas as pd
from zedda._adapters.registry import AdapterRegistry
from zedda._adapters.csv_adapter import CSVAdapter
from zedda._adapters.dataframe_adapter import DataFrameAdapter
from zedda._schema import DataType
from zedda._models import ZeddaError

def test_registry_resolves_csv(tmp_path):
    p = tmp_path / "test.csv"
    p.write_text("a,b\n1,2")
    
    adapter = AdapterRegistry.resolve(str(p))
    assert isinstance(adapter, CSVAdapter)
    
def test_registry_resolves_dataframe():
    df = pd.DataFrame({"a": [1, 2]})
    adapter = AdapterRegistry.resolve(df)
    assert isinstance(adapter, DataFrameAdapter)
    
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
    assert schema.columns[0].type == DataType.INT32
    assert schema.columns[1].name == "b"
    assert schema.columns[1].type == DataType.FLOAT64
    assert schema.columns[2].name == "c"
    assert schema.columns[2].type == DataType.STRING
