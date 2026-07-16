"""
zedda._resolve — input resolution helpers.

FIX Batch 7: Extracted from __init__.py to reduce module size and
isolate the DataFrame→temp-file path resolution logic.
Internal — not part of the public API.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


class ZeddaError(Exception):
    """Base class for all exceptions raised by zedda."""

    pass


def require_pyarrow() -> None:
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet  # noqa: F401
    except ImportError as e:
        raise ZeddaError(
            "Parquet/Arrow support requires pyarrow, which is not "
            "installed. Install it with: pip install zedda[parquet]\n"
            "CSV support works without this extra."
        ) from e


def write_temp_arrow(df) -> str:
    """Write a pandas DataFrame to a temporary Parquet file."""
    require_pyarrow()
    import pyarrow as pa
    import pyarrow.parquet as pq

    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    tmp.close()
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, tmp.name)
    return tmp.name


def write_temp_arrow_polars(df) -> str:
    """Write a polars DataFrame to a temporary Parquet file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    tmp.close()
    df.write_parquet(tmp.name)
    return tmp.name


def resolve_input(data: Any) -> tuple[str, bool]:
    """Resolve input to (file_path_str, is_temp_file) tuple.

    Accepts str/Path (passed through) or pandas/polars DataFrame
    (written to a temp Arrow IPC file).
    """
    if isinstance(data, (str, Path)):
        return str(data), False
    try:
        import pandas as pd
    except ImportError:
        pd = None

    if (pd is not None and isinstance(data, pd.DataFrame)) or (
        type(data).__name__ in ("DataFrame", "SilentDataFrame")
        and "pandas" in getattr(type(data), "__module__", "")
    ):
        try:
            return write_temp_arrow(data), True
        except Exception as e:
            raise ZeddaError(f"Failed to process pandas DataFrame: {e}") from e

    try:
        import polars as pl
    except ImportError:
        pl = None

    if (pl is not None and isinstance(data, pl.DataFrame)) or (
        type(data).__name__ == "DataFrame"
        and "polars" in getattr(type(data), "__module__", "")
    ):
        try:
            return write_temp_arrow_polars(data), True
        except Exception as e:
            raise ZeddaError(f"Failed to process polars DataFrame: {e}") from e

    raise ZeddaError(
        f"Unsupported input type: {type(data).__name__}. "
        "Expected file path (str/Path) or pandas/polars DataFrame."
    )


def cleanup_temp(path: str) -> None:
    """Silently delete a temporary file."""
    try:
        os.unlink(path)
    except OSError:
        pass
