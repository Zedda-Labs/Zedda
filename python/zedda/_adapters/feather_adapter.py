from __future__ import annotations

import ctypes
from collections.abc import Iterator

from .. import fasteda_core as _core
from .._errors import ZeddaError
from .._models import InputMeta
from .._schema import ColumnSchema, DatasetSchema, DataType, LogicalRecord
from . import InputAdapter
from ._arrow_utils import empty_record_batch

try:
    import pyarrow as pa
    import pyarrow.feather as feather
except ImportError:
    pa = None
    feather = None


class FeatherAdapter(InputAdapter):
    """Feather InputAdapter — C++-kernel-delegation pattern.

    Reads .feather files via PyArrow Feather (v1/v2) and delegates
    to C++ ArrowProfiler.

    ARCHITECTURAL TRADE-OFF NOTE (Phase 4):

    Per approved Phase 4 spec (Task 4.3), this adapter uses `pyarrow.feather.read_table()`,
    which materializes the PyArrow table structure in memory before converting to batches.
    True low-memory streaming for Feather files is deferred to a future optimization phase.
    """

    supported_types = ["feather"]
    unsupported_types = []

    def __init__(
        self,
        path: str,
        is_sampled: bool = False,
        sample_size: int = 1000000,
        correlate: bool = False,
        **kwargs,
    ):
        self.path = path
        self.is_sampled = is_sampled
        self.sample_size = sample_size
        self.correlate = correlate
        self._profile = None
        self._total_rows = 0
        self._rows_examined = 0

    def open(self) -> None:
        if feather is None:
            raise ImportError("pyarrow is required for FeatherAdapter")

        table = feather.read_table(self.path)
        self._total_rows = table.num_rows

        if self.is_sampled and self.sample_size <= 0:
            raise ValueError("sample_size must be greater than zero")
        rows_to_read = (
            min(self.sample_size, self._total_rows)
            if self.is_sampled
            else self._total_rows
        )
        is_actually_sampled = rows_to_read < self._total_rows
        profiler = _core.ArrowProfiler(self.path, self._total_rows)

        rows_read = 0
        for batch in table.to_batches(max_chunksize=65536):
            if rows_read >= rows_to_read:
                break
            if batch.num_rows > rows_to_read - rows_read:
                batch = batch.slice(0, rows_to_read - rows_read)
            rows_read += batch.num_rows
            schema_buf = (ctypes.c_uint8 * 1024)()
            array_buf = (ctypes.c_uint8 * 1024)()
            ptr_schema = ctypes.addressof(schema_buf)
            ptr_array = ctypes.addressof(array_buf)
            batch._export_to_c(ptr_array, ptr_schema)
            profiler.consume_batch(ptr_schema, ptr_array)

        if rows_read == 0:
            batch = empty_record_batch(table.schema)
            schema_buf = (ctypes.c_uint8 * 1024)()
            array_buf = (ctypes.c_uint8 * 1024)()
            batch._export_to_c(
                ctypes.addressof(array_buf), ctypes.addressof(schema_buf)
            )
            profiler.consume_batch(
                ctypes.addressof(schema_buf), ctypes.addressof(array_buf)
            )

        self._profile = profiler.finalize()
        self._profile.num_rows = self._total_rows
        self._profile.is_sampled = is_actually_sampled
        self.is_sampled = is_actually_sampled
        self._rows_examined = rows_read

    def schema(self) -> DatasetSchema:
        if not self._profile:
            self.open()

        cols = []
        for c in self._profile.columns:
            cols.append(
                ColumnSchema(name=c.name, type=DataType.from_string(c.type_str))
            )
        return DatasetSchema(columns=cols)

    def coverage(self) -> InputMeta:
        if not self._profile:
            self.open()

        return InputMeta(
            source_path=self.path,
            source_type="file",
            format="feather",
            row_count=self._total_rows,
            column_count=self._profile.num_cols,
            coverage_fraction=(
                self._rows_examined / max(1, self._total_rows)
                if self._profile.is_sampled
                else 1.0
            ),
            unsupported_types=sorted(
                {
                    unsupported
                    for column in self._profile.columns
                    for unsupported in getattr(column, "unsupported_types", [])
                }
            ),
        )

    def records(self) -> Iterator[LogicalRecord]:
        raise NotImplementedError(
            "FeatherAdapter delegates profiling to the C++ kernel (ArrowProfiler). "
            "Row-level iteration is not available; use schema() and coverage() to obtain "
            "results. See InputAdapter docstring for the kernel-delegation contract."
        )

    def close(self) -> None:
        self._profile = None
