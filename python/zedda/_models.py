from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MetricStatus(str, Enum):
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"
    SAMPLED = "SAMPLED"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"


import json


@dataclass(frozen=True)
class Coverage:
    rows_examined: int
    rows_total: int | None  # None means UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_examined": self.rows_examined,
            "rows_total": self.rows_total,
        }


@dataclass(frozen=True)
class Metric:
    value: Any
    status: MetricStatus
    coverage: Coverage
    method: str
    confidence: float | None = None
    sample_size: int | None = None
    parse_errors: int = 0
    unsupported_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "status": self.status.value
            if isinstance(self.status, Enum)
            else str(self.status),
            "coverage": self.coverage.to_dict() if self.coverage else None,
            "method": self.method,
            "confidence": self.confidence,
            "sample_size": self.sample_size,
            "parse_errors": self.parse_errors,
            "unsupported_fields": self.unsupported_fields,
        }


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    type_str: str
    metrics: dict[str, Metric] = field(default_factory=dict)
    top_values: list[Any] = field(default_factory=list)
    histogram_bins_val: list[int] = field(default_factory=list, repr=False)
    skewness_val: float = field(default=0.0, repr=False)
    kurtosis_val: float = field(default=0.0, repr=False)
    exact_numeric_overflowed_val: bool = field(default=False, repr=False)
    distinct_overflowed_val: bool = field(default=False, repr=False)
    distinct_values_val: list[Any] = field(default_factory=list, repr=False)

    @property
    def distinct_values(self) -> list[Any]:
        return self.distinct_values_val

    @property
    def type(self) -> str:
        return self.type_str

    @property
    def val_min(self) -> Any:
        m = self.metrics.get("min")
        return m.value if m else None

    @property
    def val_max(self) -> Any:
        m = self.metrics.get("max")
        return m.value if m else None

    @property
    def mean(self) -> Any:
        m = self.metrics.get("mean")
        return m.value if m else None

    @property
    def std(self) -> Any:
        m = self.metrics.get("std")
        return m.value if m else None

    @property
    def type_mismatch_count(self) -> int:
        m = self.metrics.get("null_pct")
        return m.parse_errors if m else 0

    @property
    def type_mismatch_pct(self) -> float:
        m = self.metrics.get("null_pct")
        if not m or not m.coverage or m.coverage.rows_total == 0:
            return 0.0
        return (m.parse_errors / m.coverage.rows_total) * 100.0

    @property
    def min_str_len(self) -> Any:
        m = self.metrics.get("min_len")
        return m.value if m else None

    @property
    def max_str_len(self) -> Any:
        m = self.metrics.get("max_len")
        return m.value if m else None

    @property
    def null_pct(self) -> float:
        m = self.metrics.get("null_pct")
        return m.value if m else 0.0

    @property
    def unique_approx(self) -> Any:
        m = self.metrics.get("unique")
        return m.value if m else None

    @property
    def unique_exact(self) -> Any:
        m = self.metrics.get("unique")
        if m and m.status == MetricStatus.EXACT:
            return m.value
        return -1

    @property
    def exact_unique_valid(self) -> bool:
        m = self.metrics.get("unique")
        return m is not None and m.status == MetricStatus.EXACT

    @property
    def total_count(self) -> int:
        if self.metrics:
            return next(iter(self.metrics.values())).coverage.rows_examined
        return 0

    @property
    def null_count(self) -> int:
        return (
            int(round(self.null_pct / 100.0 * self.total_count))
            if self.total_count > 0
            else 0
        )

    @property
    def non_null_count(self) -> int:
        return max(0, self.total_count - self.null_count)

    @property
    def stddev(self) -> Any:
        return self.std

    @property
    def mean_str_len(self) -> Any:
        m = self.metrics.get("mean_len")
        return m.value if m else 0.0

    @property
    def skewness(self) -> float:
        return self.skewness_val

    @property
    def kurtosis(self) -> float:
        return self.kurtosis_val

    @property
    def histogram_bins(self) -> list[int]:
        return self.histogram_bins_val

    @property
    def exact_numeric_overflowed(self) -> bool:
        return self.exact_numeric_overflowed_val

    @property
    def distinct_overflowed(self) -> bool:
        return self.distinct_overflowed_val

    @property
    def has_high_nulls(self) -> bool:
        return self.null_pct > 20.0

    @property
    def is_constant(self) -> bool:
        return self.unique_exact == 1 or self.unique_approx == 1

    @property
    def unique_pct(self) -> float:
        if self.unique_approx is not None and self.total_count > 0:
            return (self.unique_approx / self.total_count) * 100.0
        return 0.0

    @property
    def is_high_cardinality(self) -> bool:
        return self.unique_pct > 90.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type_str,
            "metrics": {k: m.to_dict() for k, m in self.metrics.items()},
            "top_values": self.top_values,
            "distinct_values": self.distinct_values,
            "distinct_overflowed": self.distinct_overflowed_val,
        }


@dataclass(frozen=True)
class DatasetProfile:
    file_name: str
    num_rows: int
    num_cols: int
    columns: list[ColumnProfile] = field(default_factory=list)
    overall_metrics: dict[str, Metric] = field(default_factory=dict)
    correlations_val: list = field(default_factory=list, repr=False)

    def __post_init__(self):
        if "\\" in self.file_name:
            object.__setattr__(self, "file_name", self.file_name.replace("\\", "/"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "num_rows": self.num_rows,
            "num_cols": self.num_cols,
            "overall_metrics": {
                k: m.to_dict() for k, m in self.overall_metrics.items()
            },
            "columns": [c.to_dict() for c in self.columns],
            "correlations": self.correlations,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @property
    def file_path(self) -> str:
        return self.file_name

    @property
    def total_null_cells(self) -> int:
        return sum(c.null_count for c in self.columns)

    @property
    def num_numeric(self) -> int:
        return len([c for c in self.columns if c.type_str in ("int", "float", "bool")])

    @property
    def num_string(self) -> int:
        return len(
            [c for c in self.columns if c.type_str not in ("int", "float", "bool")]
        )

    @property
    def is_sampled(self) -> bool:
        return any(
            m.status == MetricStatus.SAMPLED for m in self.overall_metrics.values()
        ) or any(
            any(m.status == MetricStatus.SAMPLED for m in c.metrics.values())
            for c in self.columns
        )

    @property
    def correlations(self) -> list:
        return self.correlations_val

    @property
    def scan_time_ms(self) -> float:
        m = self.overall_metrics.get("scan_time_ms")
        return float(m.value) if m and m.value is not None else 0.0

    @property
    def overall_null_pct(self) -> float:
        m = self.overall_metrics.get("null_pct")
        return m.value if m else 0.0

    @property
    def columns_dict(self) -> dict[str, ColumnProfile]:
        return {c.name: c for c in self.columns}


class ValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class RuleResult:
    evaluated: bool
    status: ValidationStatus
    reason: str | None = None
    violating_row_sample: list[Any] | None = None
    violating_row_count: int | None = None

    def __post_init__(self):
        if not self.evaluated and self.status != ValidationStatus.INDETERMINATE:
            # We use object.__setattr__ because the class is frozen
            object.__setattr__(self, "status", ValidationStatus.INDETERMINATE)
            if self.reason is None:
                object.__setattr__(self, "reason", "Rule was not evaluated")


@dataclass(frozen=True)
class Change:
    column: str
    operation: str
    rationale: str
    reversible: bool


@dataclass(frozen=True)
class CleaningPlan:
    proposed_changes: list[Change]
    generated_from: str  # ID or reference to the ProfileResult
    requires_approval: bool = True
    dry_run: bool = True


class CleanExecutionStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


@dataclass(frozen=True)
class CleanExecution:
    plan_id: str
    approved_by: str
    steps: list[str] = field(
        default_factory=lambda: [
            "write_temp_output",
            "post_write_validate",
            "fsync",
            "atomic_replace",
            "write_versioned_backup",
            "write_rollback_manifest",
        ]
    )
    status: CleanExecutionStatus = CleanExecutionStatus.PENDING


@dataclass(frozen=True)
class InputMeta:
    source_path: str
    source_type: str
    format: str
    row_count: int | None
    column_count: int
    coverage_fraction: float
    unsupported_types: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
