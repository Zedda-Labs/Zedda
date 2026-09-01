from __future__ import annotations

import ctypes
import time
from collections.abc import Iterator

from .. import fasteda_core as _core
from .._models import Coverage, InputMeta, Metric, MetricStatus
from .._schema import ColumnSchema, DatasetSchema, DataType, LogicalRecord
from . import InputAdapter
from ._arrow_utils import empty_record_batch

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = None
    pq = None


class ParquetAdapter(InputAdapter):
    """Parquet InputAdapter — C++-kernel-delegation pattern.

    Delegates parsing and stat accumulation to ArrowProfiler in C++.
    Extracts footer stats directly for EXACT min/max/nulls.
    """

    supported_types = ["parquet"]
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
        self._footer_metrics = {}
        self._total_rows = 0
        self._num_row_groups = 0
        self._final_is_sampled = False
        self._rows_examined = 0

    def open(self) -> None:
        if pq is None:
            raise ImportError("pyarrow is required for ParquetAdapter")

        self.pf = pq.ParquetFile(self.path)
        self._total_rows = self.pf.metadata.num_rows
        self._num_row_groups = self.pf.metadata.num_row_groups

        if (
            not self.is_sampled
            or self._total_rows == 0
            or self.sample_size >= self._total_rows
            or self._num_row_groups <= 6
        ):
            self.selected_groups = list(range(self._num_row_groups))
        else:
            mid = self._num_row_groups // 2
            self.selected_groups = sorted(
                {0, 1, mid - 1, mid, self._num_row_groups - 2, self._num_row_groups - 1}
            )

        rows_to_read = (
            min(self.sample_size, self._total_rows)
            if self.is_sampled
            else self._total_rows
        )
        if self.is_sampled and self.sample_size <= 0:
            raise ValueError("sample_size must be greater than zero")

        profiler = _core.ArrowProfiler(self.path, self._total_rows)

        # Stream row groups
        rows_read = 0
        for rg_idx in self.selected_groups:
            if rows_read >= rows_to_read:
                break
            rg = self.pf.read_row_group(rg_idx)
            for batch in rg.to_batches(max_chunksize=65536):
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
                if not ptr_schema or not ptr_array:
                    raise RuntimeError(
                        "Arrow C Data Interface export produced null pointers"
                    )
                profiler.consume_batch(ptr_schema, ptr_array)

        if rows_read == 0:
            batch = empty_record_batch(self.pf.schema_arrow)
            schema_buf = (ctypes.c_uint8 * 1024)()
            array_buf = (ctypes.c_uint8 * 1024)()
            batch._export_to_c(
                ctypes.addressof(array_buf), ctypes.addressof(schema_buf)
            )
            profiler.consume_batch(
                ctypes.addressof(schema_buf), ctypes.addressof(array_buf)
            )

        self._profile = profiler.finalize()
        self._rows_examined = rows_read
        self._final_is_sampled = rows_read < self._total_rows
        self._profile.is_sampled = self._final_is_sampled

        # Parquet Footer Cheat Code: Extract EXACT stats
        num_cols = self._profile.num_cols

        for i in range(num_cols):
            exact_nulls = 0
            exact_min = None
            exact_max = None
            footer_ok = True

            for rg_idx in range(self._num_row_groups):
                try:
                    col_meta = self.pf.metadata.row_group(rg_idx).column(i)
                    stats = col_meta.statistics
                    if stats is None:
                        footer_ok = False
                        break
                    exact_nulls += stats.null_count
                    if stats.has_min_max:
                        cmin, cmax = stats.min, stats.max
                        if cmin is not None:
                            exact_min = (
                                cmin if exact_min is None else min(exact_min, cmin)
                            )
                        if cmax is not None:
                            exact_max = (
                                cmax if exact_max is None else max(exact_max, cmax)
                            )
                except Exception:
                    footer_ok = False
                    break

            if footer_ok:
                col_name = self._profile.columns[i].name
                metrics = {}
                coverage = Coverage(
                    rows_examined=self._total_rows, rows_total=self._total_rows
                )

                metrics["null_count"] = Metric(
                    value=exact_nulls,
                    status=MetricStatus.EXACT,
                    coverage=coverage,
                    method="parquet_footer",
                )
                metrics["null_pct"] = Metric(
                    value=(exact_nulls / max(self._total_rows, 1)) * 100.0,
                    status=MetricStatus.EXACT,
                    coverage=coverage,
                    method="parquet_footer",
                )

                if exact_min is not None and isinstance(exact_min, (int, float)):
                    metrics["min"] = Metric(
                        value=float(exact_min),
                        status=MetricStatus.EXACT,
                        coverage=coverage,
                        method="parquet_footer",
                    )
                if exact_max is not None and isinstance(exact_max, (int, float)):
                    metrics["max"] = Metric(
                        value=float(exact_max),
                        status=MetricStatus.EXACT,
                        coverage=coverage,
                        method="parquet_footer",
                    )

                self._footer_metrics[col_name] = metrics

    def schema(self) -> DatasetSchema:
        if not self._profile:
            self.open()

        cols = []
        for c in self._profile.columns:
            # We embed footer metrics into ColumnSchema metadata
            # so they can be merged downstream.
            meta = {}
            if c.name in self._footer_metrics:
                meta["footer_metrics"] = self._footer_metrics[c.name]

            cols.append(
                ColumnSchema(
                    name=c.name, type=DataType.from_string(c.type_str), metadata=meta
                )
            )
        return DatasetSchema(columns=cols)

    def coverage(self) -> InputMeta:
        if not self._profile:
            self.open()

        return InputMeta(
            source_path=self.path,
            source_type="file",
            format="parquet",
            row_count=self._total_rows,
            column_count=self._profile.num_cols,
            coverage_fraction=(
                self._rows_examined / max(1, self._total_rows)
                if self._final_is_sampled
                else 1.0
            ),
            unsupported_types=sorted(
                {
                    unsupported
                    for column in self._profile.columns
                    for unsupported in getattr(column, "unsupported_types", [])
                }
            ),
            metadata={
                "row_group_count": self._num_row_groups,
                "sampled_row_groups": self.selected_groups,
                "rows_examined": self._rows_examined,
                "footer_stats_available": len(self._footer_metrics) > 0,
                "is_sampled": self._final_is_sampled,
            },
        )

    def records(self) -> Iterator[LogicalRecord]:
        raise NotImplementedError(
            "ParquetAdapter delegates profiling to the C++ kernel (ArrowProfiler). "
            "Row-level iteration is not available; use schema() and coverage() to obtain "
            "results. See InputAdapter docstring for the kernel-delegation contract."
        )

    def close(self) -> None:
        self._profile = None
        self.pf = None
