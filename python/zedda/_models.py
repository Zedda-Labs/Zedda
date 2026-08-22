from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Dict

class MetricStatus(str, Enum):
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"
    SAMPLED = "SAMPLED"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"

@dataclass(frozen=True)
class Coverage:
    rows_examined: int
    rows_total: Optional[int]  # None means UNKNOWN

@dataclass(frozen=True)
class Metric:
    value: Any
    status: MetricStatus
    coverage: Coverage
    method: str
    confidence: Optional[float] = None
    sample_size: Optional[int] = None
    parse_errors: int = 0
    unsupported_fields: List[str] = field(default_factory=list)

@dataclass(frozen=True)
class ColumnProfile:
    name: str
    type_str: str
    metrics: Dict[str, Metric] = field(default_factory=dict)

@dataclass(frozen=True)
class DatasetProfile:
    file_name: str
    num_rows: int
    num_cols: int
    columns: List[ColumnProfile] = field(default_factory=list)
    overall_metrics: Dict[str, Metric] = field(default_factory=dict)

class ValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INDETERMINATE = "INDETERMINATE"

@dataclass(frozen=True)
class RuleResult:
    evaluated: bool
    status: ValidationStatus
    reason: Optional[str] = None
    violating_row_sample: Optional[List[Any]] = None
    violating_row_count: Optional[int] = None

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
    proposed_changes: List[Change]
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
    steps: List[str] = field(default_factory=lambda: [
        "write_temp_output",
        "post_write_validate",
        "fsync",
        "atomic_replace",
        "write_versioned_backup",
        "write_rollback_manifest"
    ])
    status: CleanExecutionStatus = CleanExecutionStatus.PENDING

@dataclass(frozen=True)
class InputMeta:
    source_path: str
    source_type: str
    format: str
    row_count: Optional[int]
    column_count: int
    coverage_fraction: float
    unsupported_types: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

