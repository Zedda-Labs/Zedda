import pytest
import pandas as pd
from zedda._adapters.arrow_ipc_adapter import ArrowIPCAdapter
from zedda._schema import DataType

try:
    import pyarrow as pa
    import pyarrow.ipc as ipc
except ImportError:
    pa = None
    ipc = None


@pytest.fixture
def arrow_ipc_file(tmp_path):
    if pa is None:
        pytest.skip("pyarrow not installed")
        
    df = pd.DataFrame({
        "id": [1, 2, 3],
        "val": [10.5, 20.0, 15.5]
    })
    table = pa.Table.from_pandas(df)
    p = tmp_path / "test.arrow"
    with pa.OSFile(str(p), 'wb') as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)
    return str(p)


def test_arrow_ipc_adapter_coverage(arrow_ipc_file):
    adapter = ArrowIPCAdapter(arrow_ipc_file)
    coverage = adapter.coverage()
    
    assert coverage.format == "arrow_ipc"
    assert coverage.row_count == 3
    assert coverage.column_count == 2


def test_arrow_ipc_adapter_schema(arrow_ipc_file):
    adapter = ArrowIPCAdapter(arrow_ipc_file)
    schema = adapter.schema()
    
    assert len(schema.columns) == 2
    assert schema.columns[0].name == "id"
    assert schema.columns[0].type == DataType.INT64
    assert schema.columns[1].name == "val"
    assert schema.columns[1].type == DataType.FLOAT64


def test_arrow_ipc_adapter_records_raises():
    if pa is None:
        pytest.skip("pyarrow not installed")
    adapter = ArrowIPCAdapter("dummy.arrow")
    with pytest.raises(NotImplementedError, match="kernel-delegation"):
        list(adapter.records())
