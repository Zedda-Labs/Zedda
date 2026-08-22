from abc import ABC, abstractmethod
from typing import List, Iterator, Any

from .._schema import DatasetSchema, LogicalRecord
from .._models import InputMeta

class InputAdapter(ABC):
    """
    Abstract base class for all data ingestion adapters.
    
    Adapters are responsible for taking a raw input source (file, dataframe, etc.)
    and emitting logical records or delegating to the C++ kernel, alongside
    schema and coverage metadata.
    """
    
    # Each adapter must declare its supported and unsupported types
    supported_types: List[str] = []
    unsupported_types: List[str] = []
    
    @abstractmethod
    def open(self) -> None:
        """Initialize the adapter and prepare the source for reading."""
        pass
        
    @abstractmethod
    def schema(self) -> DatasetSchema:
        """Return the schema of the dataset."""
        pass
        
    @abstractmethod
    def coverage(self) -> InputMeta:
        """Return coverage metadata (e.g. exact vs estimated row count, errors)."""
        pass
        
    @abstractmethod
    def records(self) -> Iterator[LogicalRecord]:
        """
        Yield logical records.
        For high-performance formats, this might just yield batches to the C++ kernel.
        """
        pass
        
    @abstractmethod
    def close(self) -> None:
        """Clean up any open resources."""
        pass
