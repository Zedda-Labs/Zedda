"""
zedda._scan — scan() and _scan_arrow() implementation.

FIX Batch 7/12: Extracted from __init__.py to reduce module size.
Internal — not part of the public API. The public scan() function in
__init__.py delegates to these helpers.
"""

from __future__ import annotations

import ctypes
import time
from pathlib import Path
from typing import Any

from ._constants import (
    ARROW_SCHEMA_SIZE as _ARROW_SCHEMA_SIZE,
    ARROW_ARRAY_SIZE as _ARROW_ARRAY_SIZE,
    sampled_info_set as _sampled_info_set,
)
from ._format import format_scan_time as _format_scan_time  # noqa: F401


class ZeddaError(Exception):
    """Re-declared here to avoid circular import with _resolve."""

    pass


def count_lines(path: str) -> int | None:
    """Count newlines in a file without reading it fully into memory.

    Returns None on any error so callers can display "unknown" rather
    than 0 (which would produce misleading "100% sampled" output).
    Adds 1 for files that don't end with a trailing newline.
    """
    try:
        count = 0
        saw_non_newline = False
        last_byte = b"\n"
        with open(path, "rb") as f:
            while True:
                chunk = f.read(4 * 1024 * 1024)
                if not chunk:
                    break
                saw_non_newline = saw_non_newline or any(b != b"\n" for b in chunk)
                count += chunk.count(b"\n")
                last_byte = chunk[-1:]
        if saw_non_newline and last_byte != b"\n":
            count += 1
        return count
    except Exception:
        return None


def scan_arrow(
    path: str,
    is_sampled: bool = False,
    sample_size: int = 1_000_000,
    core_module: Any = None,
) -> Any:
    """Zero-copy Parquet → C++ via Arrow C Data Interface.

    Phase 3 features:
      - Stratified row-group sampling (reads only 6 representative groups)
      - Parquet Footer Cheat Code: exact nulls/min/max from metadata
      - Confidence intervals in terminal output when sampled

    Args:
        path: Path to the Parquet/Arrow file.
        is_sampled: Whether sampling is active.
        sample_size: Max rows to sample.
        core_module: The C++ extension module (fasteda_core).
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:
        raise ZeddaError(
            "Parquet/Arrow support requires pyarrow. "
            "Install with: pip install zedda[parquet]"
        ) from e

    t0 = time.perf_counter()
    pf = pq.ParquetFile(path)

    total_rows = pf.metadata.num_rows
    num_row_groups = pf.metadata.num_row_groups

    # ── Stratified sampling: pick 6 representative row groups ─────
    if num_row_groups <= 6 or not is_sampled:
        selected_groups = list(range(num_row_groups))
        final_is_sampled = False
    else:
        mid = num_row_groups // 2
        selected_groups = sorted(
            {0, 1, mid - 1, mid, num_row_groups - 2, num_row_groups - 1}
        )
        final_is_sampled = True

    profiler = core_module.ArrowProfiler(path, total_rows)

    # ── Stream selected row groups to C++ via Arrow C Data Interface ──
    for rg_idx in selected_groups:
        rg = pf.read_row_group(rg_idx)
        for batch in rg.to_batches(max_chunksize=65_536):
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

    # ── Parquet Footer Cheat Code ─────────────────────────────────
    num_cols = profile_obj.num_cols
    for i in range(num_cols):
        exact_nulls = 0
        exact_min = None
        exact_max = None
        footer_ok = True

        for rg_idx in range(num_row_groups):
            try:
                col_meta = pf.metadata.row_group(rg_idx).column(i)
                stats = col_meta.statistics
                if stats is None:
                    footer_ok = False
                    break
                exact_nulls += stats.null_count
                if stats.has_min_max:
                    cmin, cmax = stats.min, stats.max
                    if cmin is not None:
                        exact_min = cmin if exact_min is None else min(exact_min, cmin)
                    if cmax is not None:
                        exact_max = cmax if exact_max is None else max(exact_max, cmax)
            except Exception:
                footer_ok = False
                break

        if footer_ok:
            col = profile_obj.columns[i]
            col.null_count = exact_nulls
            col.null_pct = (exact_nulls / total_rows * 100.0) if total_rows > 0 else 0.0
            col.non_null_count = total_rows - exact_nulls
            col.has_high_nulls = col.null_pct > 20.0
            if (
                exact_min is not None
                and exact_max is not None
                and isinstance(exact_min, (int, float))
                and isinstance(exact_max, (int, float))
            ):
                col.val_min = float(exact_min)
                col.val_max = float(exact_max)
                col.range = float(exact_max) - float(exact_min)

    profile_obj.scan_time_ms = (time.perf_counter() - t0) * 1000.0
    profile_obj.is_sampled = final_is_sampled

    if final_is_sampled:
        scanned_rows = profile_obj.num_rows
        _sampled_info_set(path, (scanned_rows, total_rows))
        profile_obj.num_rows = scanned_rows
    else:
        profile_obj.num_rows = total_rows

    return profile_obj
