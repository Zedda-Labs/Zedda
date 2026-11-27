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


from ._errors import ZeddaError


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
        pl: Any = None  # type: ignore[no-redef]

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


def load_dataframe(source: Any, columns: list[str] | None = None):
    """Load a pandas DataFrame from a file path or pandas/polars DataFrame.

    Supports CSV/TXT/TSV, Parquet (.parquet, .pq), Arrow IPC (.arrow, .ipc),
    Feather (.feather), and in-memory pandas/polars DataFrames.
    """
    import pandas as pd

    if hasattr(source, "to_pandas") and not isinstance(source, (str, Path)):
        df = source.to_pandas()
        return df[columns] if columns is not None else df
    if hasattr(source, "copy") and not isinstance(source, (str, Path)):
        return source[columns].copy() if columns is not None else source.copy()

    resolved_str = str(source)
    ext = Path(resolved_str).suffix.lower()

    if ext in (".csv", ".txt", ".tsv"):
        sep = "\t" if ext == ".tsv" else ","
        return pd.read_csv(resolved_str, sep=sep, usecols=columns)
    if ext in (".parquet", ".pq"):
        return pd.read_parquet(resolved_str, columns=columns)
    if ext in (".arrow", ".ipc"):
        require_pyarrow()
        import pyarrow as pa
        import pyarrow.ipc as ipc

        try:
            with pa.OSFile(resolved_str, "rb") as f:
                table = ipc.open_file(f).read_all()
            if columns is not None:
                table = table.select(columns)
            return table.to_pandas()
        except Exception:
            import pyarrow.feather as feather

            table = feather.read_table(resolved_str, columns=columns)
            return table.to_pandas()
    if ext == ".feather":
        require_pyarrow()
        import pyarrow.feather as feather

        return feather.read_table(resolved_str, columns=columns).to_pandas()

    raise ZeddaError(f"Unsupported format: {ext}")
