from __future__ import annotations

import ctypes
import time
from collections.abc import Iterator
from typing import Any

from .. import fasteda_core as _core
from .._constants import ARROW_ARRAY_SIZE as _ARROW_ARRAY_SIZE
from .._constants import ARROW_SCHEMA_SIZE as _ARROW_SCHEMA_SIZE
from .._models import InputMeta
from .._schema import ColumnSchema, DatasetSchema, DataType, LogicalRecord
from . import InputAdapter


class DataFrameAdapter(InputAdapter):
    """
    DataFrame InputAdapter — C++-kernel-delegation pattern.

    Wraps an in-memory DataFrame (currently Pandas only) and delegates profiling
    directly to the C++ ArrowProfiler via the Arrow C Data Interface.
    Zero disk I/O. Coverage is always EXACT (full materialized data).

    **Polars support:** Polars support is formally DEFERRED to Phase 4/5.
    Passing a Polars DataFrame raises ``NotImplementedError``.

    Delegation contract:
    - ``open()``     → Converts to PyArrow Table and streams to ``ArrowProfiler``
    - ``schema()``   → Extracted from C++ ProfileResult
    - ``coverage()`` → Returns InputMeta from C++ ProfileResult
    - ``records()``  → Raises ``NotImplementedError`` (kernel-delegation pattern)
    - ``close()``    → Resets C++ profile reference
    """

    supported_types = ["dataframe"]
    unsupported_types = []

    def __init__(self, df: Any, **kwargs):
        self.df = df
        self.correlate = kwargs.get("correlate", False)
        self.sample_size = kwargs.get("sample_size")
        self._profile = None

        # Check if pandas
        self._is_pandas = (
            hasattr(df, "columns")
            and hasattr(df, "dtypes")
            and hasattr(df, "itertuples")
        )
        if not self._is_pandas:
            if hasattr(df, "columns") and hasattr(df, "dtypes"):
                raise NotImplementedError(
                    "Polars DataFrame support in DataFrameAdapter is deferred to Phase 4/5. "
                    "Convert to Pandas with df.to_pandas() as a workaround, or await Phase 4."
                )
            raise TypeError(
                "DataFrameAdapter requires a Pandas DataFrame. "
                "Polars support is deferred to Phase 4/5."
            )

    def open(self) -> None:
        try:
            import pyarrow as pa
        except ImportError as e:
            raise TypeError("PyArrow is required for DataFrame profiling.") from e

        t0 = time.perf_counter()
        
        total_rows = len(self.df)
        target_df = self.df
        is_actually_sampled = False
        
        if self.sample_size is not None and self.sample_size < total_rows:
            target_df = self.df.head(self.sample_size)
            is_actually_sampled = True

        table = pa.Table.from_pandas(target_df, preserve_index=False)
        display_name = "<DataFrame>"

        profiler = _core.ArrowProfiler(display_name, total_rows)

        for batch in table.to_batches(max_chunksize=65_536):
            schema_buf = (ctypes.c_uint8 * _ARROW_SCHEMA_SIZE)()
            array_buf = (ctypes.c_uint8 * _ARROW_ARRAY_SIZE)()

            ptr_schema = ctypes.addressof(schema_buf)
            ptr_array = ctypes.addressof(array_buf)

            batch._export_to_c(ptr_array, ptr_schema)

            if not ptr_schema or not ptr_array:
                raise RuntimeError(
                    "Arrow C Data Interface export produced null pointers "
                    f"(schema={ptr_schema:#x}, array={ptr_array:#x})"
                )

            profiler.consume_batch(ptr_schema, ptr_array)
            del schema_buf, array_buf

        profile_obj = profiler.finalize()
        profile_obj.num_rows = total_rows
        profile_obj.is_sampled = is_actually_sampled
        profile_obj.scan_time_ms = (time.perf_counter() - t0) * 1000.0
        profile_obj.file_name = display_name
        profile_obj.file_path = display_name

        self._profile = profile_obj

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
            source_path="<DataFrame>",
            source_type="memory",
            format="dataframe",
            row_count=self._profile.num_rows if self._profile else 0,
            column_count=self._profile.num_cols if self._profile else 0,
            coverage_fraction=(
                self.sample_size / self._profile.num_rows
                if getattr(self._profile, "is_sampled", False)
                and self.sample_size is not None
                and self._profile.num_rows > 0
                else 1.0
            ),
            unsupported_types=[],
        )

    def records(self) -> Iterator[LogicalRecord]:
        raise NotImplementedError(
            "DataFrameAdapter uses the C++-kernel-delegation pattern for maximum performance. "
            "It streams Arrow batches directly into the C++ ArrowProfiler and does not "
            "yield Python LogicalRecord objects. To validate records row-by-row, use a "
            "separate streaming evidence pass over the original source."
        )

    def close(self) -> None:
        self._profile = None
