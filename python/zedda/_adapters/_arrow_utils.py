from __future__ import annotations

from typing import Any


def empty_record_batch(schema: Any) -> Any:
    """Build a zero-row batch that preserves an Arrow schema."""
    import pyarrow as pa

    arrays = [pa.array([], type=field.type) for field in schema]
    return pa.RecordBatch.from_arrays(arrays, schema=schema)


def extract_parquet_column_footer_stats(
    pf: Any, col_idx: int, col_name: str, num_row_groups: int
) -> tuple[bool, int, Any, Any]:
    """Extract aggregated Parquet footer (ok, null_count, min, max) safely for a flat column.

    Skips nested/compound columns (struct/list/map) and resolves physical leaf
    columns by ``path_in_schema`` so nested fields earlier in the table cannot
    shift column indices for subsequent top-level columns.
    """
    import pyarrow as pa

    try:
        arrow_field = pf.schema_arrow.field(col_idx)
        if pa.types.is_nested(arrow_field.type):
            return False, 0, None, None
    except Exception:
        return False, 0, None, None

    exact_nulls = 0
    exact_min = None
    exact_max = None

    for rg_idx in range(num_row_groups):
        try:
            rg_meta = pf.metadata.row_group(rg_idx)
            col_meta = None
            if (
                col_idx < rg_meta.num_columns
                and rg_meta.column(col_idx).path_in_schema == col_name
            ):
                col_meta = rg_meta.column(col_idx)
            else:
                for leaf_idx in range(rg_meta.num_columns):
                    candidate = rg_meta.column(leaf_idx)
                    if candidate.path_in_schema == col_name:
                        col_meta = candidate
                        break
            if col_meta is None:
                return False, 0, None, None
            stats = col_meta.statistics
            if stats is None:
                return False, 0, None, None
            exact_nulls += stats.null_count
            if stats.has_min_max:
                cmin, cmax = stats.min, stats.max
                if cmin is not None:
                    exact_min = cmin if exact_min is None else min(exact_min, cmin)
                if cmax is not None:
                    exact_max = cmax if exact_max is None else max(exact_max, cmax)
        except Exception:
            return False, 0, None, None

    return True, exact_nulls, exact_min, exact_max
