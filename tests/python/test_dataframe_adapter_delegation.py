import pytest
import pandas as pd
from zedda._adapters.dataframe_adapter import DataFrameAdapter
from zedda._adapters.registry import AdapterRegistry

def test_dataframe_adapter_cpp_delegation():
    df = pd.DataFrame({
        "a": [1, 2, 3],
        "b": ["x", "y", "z"],
        "c": [True, False, True]
    })
    
    adapter = AdapterRegistry.resolve(df)
    assert isinstance(adapter, DataFrameAdapter)
    
    # Must raise NotImplementedError for records
    with pytest.raises(NotImplementedError):
        list(adapter.records())
        
    adapter.open()
    assert adapter._profile is not None
    assert adapter._profile.num_rows == 3
    assert adapter._profile.num_cols == 3
    
    schema = adapter.schema()
    assert len(schema.columns) == 3
    
    coverage = adapter.coverage()
    assert coverage.row_count == 3
    
    adapter.close()
    assert adapter._profile is None
