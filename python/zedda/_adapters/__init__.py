from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from .._errors import ZeddaError
from .._models import InputMeta
from .._schema import DatasetSchema, LogicalRecord


class InputAdapter(ABC):
    """Abstract base class for all data ingestion adapters.

    Adapters are responsible for taking a raw input source (file, dataframe, etc.)
    and emitting schema + coverage metadata. They must also define a records()
    iteration strategy.

    There are two valid delegation patterns for records():

    1. **Python-row-iterator pattern**: The adapter yields ``LogicalRecord`` objects
       that flow through the canonical record stream into the profiling kernel.
       Suited for in-memory sources (DataFrames) and custom parsers.

    2. **C++-kernel-delegation pattern**: The adapter delegates ALL data movement
       to the C++ ``ProfileBuilder`` / ``ArrowProfiler`` directly, bypassing Python
       row iteration entirely for throughput reasons (e.g. CSVAdapter, ParquetAdapter).
       In this pattern, ``records()`` MUST raise ``NotImplementedError`` with a clear
       message explaining the delegation, so callers cannot silently receive wrong data.
       The contract is satisfied by documenting and testing this delegation explicitly.

    Subclasses MUST implement open(), schema(), coverage(), and close().
    Subclasses MUST implement records() in one of the two patterns above.
    Raising ``NotImplementedError`` in records() is only valid for kernel-delegating
    adapters, and it MUST be documented in the subclass docstring.
    """

    # Each adapter must declare its supported and unsupported types
    supported_types: list[str] = []
    unsupported_types: list[str] = []

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
        Yield logical records for downstream consumers.

        KERNEL-DELEGATING ADAPTERS: If this adapter delegates profiling directly
        to the C++ kernel (e.g. CSVAdapter, ParquetAdapter), raise
        ``NotImplementedError`` with a message explaining the delegation.
        This is the only valid reason to not yield records; it must be tested
        and documented explicitly in the subclass.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Clean up any open resources."""
        pass
