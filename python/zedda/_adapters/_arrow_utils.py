from __future__ import annotations

from typing import Any


def empty_record_batch(schema: Any) -> Any:
    """Build a zero-row batch that preserves an Arrow schema."""
    import pyarrow as pa

    arrays = [pa.array([], type=field.type) for field in schema]
    return pa.RecordBatch.from_arrays(arrays, schema=schema)
