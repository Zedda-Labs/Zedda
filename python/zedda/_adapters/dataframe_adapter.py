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
from ._arrow_utils import empty_record_batch


class DataFrameAdapter(InputAdapter):
    """
    DataFrame InputAdapter — C++-kernel-delegation pattern.

    Wraps an in-memory pandas or Polars DataFrame and delegates profiling
    directly to the C++ ArrowProfiler via the Arrow C Data Interface.
    Zero disk I/O. Coverage is always EXACT (full materialized data).

    Delegation contract:
    - ``open()``     → Converts to PyArrow Table and streams to ``ArrowProfiler``
    - ``schema()``   → Extracted from C++ ProfileResult
    - ``coverage()`` → Returns InputMeta from C++ ProfileResult
    - ``records()``  → Raises ``NotImplementedError`` (kernel-delegation pattern)
    - ``close()``    → Resets C++ profile reference
    """

    supported_types = ["dataframe"]
    unsupported_types = []
    _EXACT_DISTINCT_CAP = 100

    def __init__(self, df: Any, **kwargs):
        self.df = df
        self.correlate = kwargs.get("correlate", False)
        self.is_sampled = kwargs.get("is_sampled", False)
        self.sample_size = kwargs.get("sample_size")
        self._profile = None
        self._exact_evidence: dict[str, dict[str, Any]] = {}

        # Check if pandas
        self._is_pandas = (
            hasattr(df, "columns")
            and hasattr(df, "dtypes")
            and hasattr(df, "itertuples")
        )
        self._is_polars = (
            not self._is_pandas
            and hasattr(df, "columns")
            and hasattr(df, "dtypes")
            and hasattr(df, "to_arrow")
        )
        if not self._is_pandas and not self._is_polars:
            if hasattr(df, "columns") and hasattr(df, "dtypes"):
                raise NotImplementedError(
                    "Unsupported DataFrame implementation. Expected pandas or Polars."
                )
            raise TypeError("DataFrameAdapter requires a pandas or Polars DataFrame.")

    def open(self) -> None:
        try:
            import pyarrow as pa
        except ImportError as e:
            raise TypeError("PyArrow is required for DataFrame profiling.") from e

        t0 = time.perf_counter()

        total_rows = len(self.df)
        target_df = self.df
        is_actually_sampled = False

        if (
            self.is_sampled
            and self.sample_size is not None
            and self.sample_size < total_rows
        ):
            target_df = self.df.head(self.sample_size)
            is_actually_sampled = True

        table = (
            pa.Table.from_pandas(target_df, preserve_index=False)
            if self._is_pandas
            else target_df.to_arrow()
        )
        display_name = "<DataFrame>"

        profiler = _core.ArrowProfiler(display_name, total_rows)

        rows_read = 0
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

        if rows_read == 0:
            batch = empty_record_batch(table.schema)
            schema_buf = (ctypes.c_uint8 * _ARROW_SCHEMA_SIZE)()
            array_buf = (ctypes.c_uint8 * _ARROW_ARRAY_SIZE)()
            batch._export_to_c(
                ctypes.addressof(array_buf), ctypes.addressof(schema_buf)
            )
            profiler.consume_batch(
                ctypes.addressof(schema_buf), ctypes.addressof(array_buf)
            )
            rows_read += batch.num_rows

        profile_obj = profiler.finalize()
        profile_obj.num_rows = total_rows
        profile_obj.is_sampled = is_actually_sampled
        profile_obj.scan_time_ms = (time.perf_counter() - t0) * 1000.0
        profile_obj.file_name = display_name
        profile_obj.file_path = display_name

        self._profile = profile_obj

        # A complete in-memory frame can provide stronger evidence than the
        # streaming Arrow profiler without making sampled frames look exact.
        if not is_actually_sampled:
            for index, column_name in enumerate(table.column_names):
                try:
                    if self._is_pandas:
                        values = target_df[column_name].dropna().unique().tolist()
                    else:
                        values = (
                            table.column(index).combine_chunks().drop_null().to_pylist()
                        )
                    distinct_values = list(dict.fromkeys(values))
                    self._exact_evidence[str(column_name)] = {
                        "unique_count": int(len(distinct_values)),
                        "distinct_values": distinct_values[: self._EXACT_DISTINCT_CAP],
                        "distinct_overflowed": len(distinct_values)
                        > self._EXACT_DISTINCT_CAP,
                    }
                except (TypeError, ValueError):
                    # Unhashable/object values cannot be represented by the
                    # bounded canonical distinct-value evidence.
                    continue

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
            "DataFrameAdapter uses the C++-kernel-delegation pattern for maximum performance. "
            "It streams Arrow batches directly into the C++ ArrowProfiler and does not "
            "yield Python LogicalRecord objects. To validate records row-by-row, use a "
            "separate streaming evidence pass over the original source."
        )

    def close(self) -> None:
        self._profile = None
        self._exact_evidence = {}
