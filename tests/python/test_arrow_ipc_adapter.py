import pytest
import pandas as pd
from unittest.mock import patch
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

    df = pd.DataFrame({"id": [1, 2, 3], "val": [10.5, 20.0, 15.5]})
    table = pa.Table.from_pandas(df)
    p = tmp_path / "test.arrow"
    with pa.OSFile(str(p), "wb") as sink, ipc.new_file(sink, table.schema) as writer:
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


def test_arrow_ipc_adapter_honors_sample_size_without_native_scan(tmp_path):
    exported_rows = []

    class FakeBatch:
        def __init__(self, rows):
            self.num_rows = rows

        def slice(self, _offset, length):
            return FakeBatch(length)

        def _export_to_c(self, _array_ptr, _schema_ptr):
            exported_rows.append(self.num_rows)

    class FakeReader:
        num_record_batches = 2
        batches = [FakeBatch(3), FakeBatch(3)]

        def get_batch(self, index):
            return self.batches[index]

    class FakeFile:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeProfile:
        num_cols = 1
        columns = []
        num_rows = 0
        is_sampled = False

    class FakeProfiler:
        def __init__(self, _path, _total_rows):
            pass

        def consume_batch(self, _schema_ptr, _array_ptr):
            pass

        def finalize(self):
            return FakeProfile()

    class FakeOSFile:
        def __new__(cls, *_args):
            return FakeFile()

    class FakePA:
        OSFile = FakeOSFile

    class FakeIPC:
        @staticmethod
        def open_file(_file):
            return FakeReader()

    adapter = ArrowIPCAdapter(str(tmp_path / "sample.arrow"), True, 4)
    with (
        patch("zedda._adapters.arrow_ipc_adapter.pa", FakePA),
        patch("zedda._adapters.arrow_ipc_adapter.ipc", FakeIPC),
        patch("zedda._adapters.arrow_ipc_adapter._core.ArrowProfiler", FakeProfiler),
    ):
        adapter.open()

    assert exported_rows == [3, 1]
    assert adapter._profile.num_rows == 6
    assert adapter._profile.is_sampled is True
    assert adapter._rows_examined == 4
    assert adapter.coverage().coverage_fraction == pytest.approx(4 / 6)
