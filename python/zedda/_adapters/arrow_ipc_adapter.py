import ctypes
from typing import Iterator

from . import InputAdapter
from .._schema import DatasetSchema, ColumnSchema, DataType, LogicalRecord
from .._models import InputMeta, ZeddaError
from .. import fasteda_core as _core

try:
    import pyarrow as pa
    import pyarrow.ipc as ipc
except ImportError:
    pa = None
    ipc = None


class ArrowIPCAdapter(InputAdapter):
    """
    Arrow IPC InputAdapter — C++-kernel-delegation pattern.
    
    Reads .arrow (Feather v2 / Arrow IPC) files via PyArrow IPC
    and delegates to C++ ArrowProfiler.
    """
    supported_types = ["arrow", "ipc"]
    unsupported_types = []

    def __init__(self, path: str, is_sampled: bool = False, sample_size: int = 1000000):
        self.path = path
        self.is_sampled = is_sampled
        self.sample_size = sample_size
        self._profile = None
        self._total_rows = 0

    def open(self) -> None:
        if ipc is None:
            raise ImportError("pyarrow is required for ArrowIPCAdapter")
            
        with pa.OSFile(self.path, 'rb') as f:
            reader = ipc.open_file(f)
            self._total_rows = 0
            
            # First pass: count total rows and create profiler
            for i in range(reader.num_record_batches):
                self._total_rows += reader.get_batch(i).num_rows
                
            profiler = _core.ArrowProfiler(self.path, self._total_rows)
            
            # Second pass: feed batches to C++
            # Wait, PyArrow IPC memory mapping might be better
            for i in range(reader.num_record_batches):
                batch = reader.get_batch(i)
                schema_buf = (ctypes.c_uint8 * 1024)()
                array_buf = (ctypes.c_uint8 * 1024)()
                ptr_schema = ctypes.addressof(schema_buf)
                ptr_array = ctypes.addressof(array_buf)
                batch._export_to_c(ptr_array, ptr_schema)
                profiler.consume_batch(ptr_schema, ptr_array)
                
            self._profile = profiler.finalize()

    def schema(self) -> DatasetSchema:
        if not self._profile:
            self.open()
            
        cols = []
        for c in self._profile.columns:
            cols.append(ColumnSchema(
                name=c.name,
                type=DataType.from_string(c.type_str)
            ))
        return DatasetSchema(columns=cols)

    def coverage(self) -> InputMeta:
        if not self._profile:
            self.open()
            
        return InputMeta(
            source_path=self.path,
            source_type="file",
            format="arrow_ipc",
            row_count=self._total_rows,
            column_count=self._profile.num_cols,
            coverage_fraction=1.0,  # We process all batches in IPC for now
            unsupported_types=[]
        )

    def records(self) -> Iterator[LogicalRecord]:
        raise NotImplementedError(
            "ArrowIPCAdapter delegates profiling to the C++ kernel (ArrowProfiler). "
            "Row-level iteration is not available; use schema() and coverage() to obtain "
            "results. See InputAdapter docstring for the kernel-delegation contract."
        )

    def close(self) -> None:
        self._profile = None
