from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class DataType(enum.Enum):
    """Canonical data types for Zedda engine."""

    # Numeric
    INT8 = "int8"
    INT16 = "int16"
    INT32 = "int32"
    INT64 = "int64"
    UINT8 = "uint8"
    UINT16 = "uint16"
    UINT32 = "uint32"
    UINT64 = "uint64"
    FLOAT16 = "float16"
    FLOAT32 = "float32"
    FLOAT64 = "float64"

    # Text / Binary
    STRING = "string"
    BINARY = "binary"

    # Temporal
    DATE = "date"  # logical date (no time)
    TIME = "time"  # logical time (no date)
    TIMESTAMP = "timestamp"  # datetime

    # Other
    BOOLEAN = "boolean"
    NULL = "null"  # all-null column
    UNKNOWN = "unknown"  # type not yet inferred or explicitly unsupported

    @classmethod
    def from_string(cls, val: str) -> DataType:
        val = val.lower()
        if val == "int":
            return cls.INT64
        if val == "float":
            return cls.FLOAT64
        if val == "str":
            return cls.STRING
        if val == "bool":
            return cls.BOOLEAN
        try:
            return cls(val)
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class ColumnSchema:
    """Schema for a single column."""

    name: str
    type: DataType
    nullable: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetSchema:
    """Schema for an entire dataset."""

    columns: list[ColumnSchema]
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_column(self, name: str) -> ColumnSchema | None:
        for col in self.columns:
            if col.name == name:
                return col
        return None

    @property
    def column_names(self) -> list[str]:
        return [col.name for col in self.columns]


@dataclass
class LogicalRecord:
    """A logical record emitted by an InputAdapter.

    For row-based iterators (like CSV fallbacks or custom parsers).
    Note: Highly-optimized adapters (like Parquet/Arrow) might bypass
    emitting individual LogicalRecords and instead pass batches directly to the kernel,
    but this struct is the canonical definition for row-based streams.
    """

    row_index: int
    values: dict[str, Any]
    is_valid: bool = True
    parse_error: str | None = None
