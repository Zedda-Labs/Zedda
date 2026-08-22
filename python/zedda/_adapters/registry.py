import os
from typing import Any, Type, Dict, Optional

from . import InputAdapter
from .csv_adapter import CSVAdapter
from .dataframe_adapter import DataFrameAdapter
from .parquet_adapter import ParquetAdapter
from .arrow_ipc_adapter import ArrowIPCAdapter
from .feather_adapter import FeatherAdapter
from .._models import ZeddaError


class AdapterRegistry:
    """
    Registry for resolving data sources to the appropriate InputAdapter.
    """
    
    _extension_map: Dict[str, Type[InputAdapter]] = {
        ".csv": CSVAdapter,
        ".txt": CSVAdapter,
        ".tsv": CSVAdapter,
        ".parquet": ParquetAdapter,
        ".pq": ParquetAdapter,
        ".arrow": ArrowIPCAdapter,
        ".ipc": ArrowIPCAdapter,
        ".feather": FeatherAdapter,
    }

    @classmethod
    def register_extension(cls, ext: str, adapter_cls: Type[InputAdapter]) -> None:
        """Register an adapter class for a specific file extension."""
        cls._extension_map[ext.lower()] = adapter_cls

    @classmethod
    def resolve(cls, source: Any, **kwargs) -> InputAdapter:
        """
        Resolve a data source to the appropriate InputAdapter instance.
        
        Raises ZeddaError for explicitly unsupported formats.
        """
        # If the source is a string or Path, treat it as a file
        if isinstance(source, str) or hasattr(source, "__fspath__"):
            path = str(source)
            if not os.path.exists(path):
                raise ZeddaError(f"File not found: {path}")
                
            _, ext = os.path.splitext(path)
            ext = ext.lower()
            
            if ext in cls._extension_map:
                adapter_cls = cls._extension_map[ext]
                return adapter_cls(path, **kwargs)
            else:
                raise ZeddaError(f"Unsupported file format: {ext}")
                
        # Handle DataFrames
        if hasattr(source, "columns") and hasattr(source, "dtypes"):
            return DataFrameAdapter(source, **kwargs)
            
        raise ZeddaError("Unsupported input type. Must be a file path or a Pandas DataFrame.")

