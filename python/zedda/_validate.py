r"""
zedda._validate — Enterprise Data Contracts & Rule-Based Validation Engine.

Phase 2 / Phase 6 Feature: Declarative data quality contracts that can be embedded
in CI/CD pipelines, data ingestion checks, and production monitoring.

Design Goals:
  - Zero-dependency (uses ZEDDA's C++ profiling engine and canonical models)
  - Declarative YAML-friendly rule format
  - Tri-state evidence-aware evaluation: PASS, FAIL, INDETERMINATE
  - Exact vs. approximate uniqueness mathematical honesty
  - CI/CD compatible: raises SystemExit(1) on critical failures if requested

Usage::

    import zedda as zd

    report = zd.validate("data.csv", rules={
        "age":    {"min": 0, "max": 150, "max_null_pct": 5.0},
        "email":  {"regex": r'^[\w.+-]+@[\w-]+\.[\w.-]+$', "is_unique": True},
        "status": {"allowed_values": ["active", "inactive", "pending"]},
        "id":     {"is_unique": True, "max_null_pct": 0.0},
    })
    print(report)
    if report.failed:
        sys.exit(1)   # fail the CI/CD pipeline
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any

from ._models import RuleResult, ValidationStatus


# ─────────────────────────────────────────────────────────────────────────────
#  RuleBreachDetail — one specific rule breach or indeterminate evaluation
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RuleBreachDetail:
    column: str
    rule: str
    expected: str
    actual: str
    severity: str  # "CRITICAL" | "WARNING" | "INDETERMINATE"
    status: ValidationStatus = ValidationStatus.FAIL
    reason: str | None = None

    def __str__(self) -> str:
        if (
            self.status == ValidationStatus.INDETERMINATE
            or self.severity == "INDETERMINATE"
        ):
            icon = "⚠️"
            sev = "INDETERMINATE"
        elif self.severity == "CRITICAL":
            icon = "🔴"
            sev = "CRITICAL"
        else:
            icon = "🟡"
            sev = "WARNING"
        return (
            f"{icon} [{sev}] Column '{self.column}' — {self.rule}: "
            f"expected {self.expected}, got {self.actual}"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  ColumnValidationResult — results for a single column
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ColumnValidationResult:
    column: str
    passed: bool
    breaches: list[RuleBreachDetail] = field(default_factory=list)
    rule_results: dict[str, RuleResult] = field(default_factory=dict)
    status: ValidationStatus = ValidationStatus.PASS

    @property
    def failed(self) -> bool:
        return self.status == ValidationStatus.FAIL or not self.passed

    @property
    def indeterminate(self) -> bool:
        return self.status == ValidationStatus.INDETERMINATE


# ─────────────────────────────────────────────────────────────────────────────
#  ValidationReport — top-level result of zd.validate()
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ValidationReport:
    """Enterprise data quality validation result."""

    columns: list[ColumnValidationResult] = field(default_factory=list)
    total_rules: int = 0
    passed_rules: int = 0
    failed_rules: int = 0
    indeterminate_rules: int = 0
    failed: bool = False
    file_name: str = "<unknown>"

    @property
    def passed(self) -> bool:
        return not self.failed and self.indeterminate_rules == 0

    @property
    def indeterminate(self) -> bool:
        return not self.failed and self.indeterminate_rules > 0

    def all_breaches(self) -> list[RuleBreachDetail]:
        return [b for cr in self.columns for b in cr.breaches]

    def __repr__(self) -> str:
        sep = "─" * 60
        lines = [
            f"\n{sep}",
            f"  ZEDDA Data Contract Validation — {self.file_name}",
            f"{sep}",
            f"  Total rules evaluated : {self.total_rules}",
            f"  ✅ Passed             : {self.passed_rules}",
            f"  ❌ Failed             : {self.failed_rules}",
        ]
        if self.indeterminate_rules > 0:
            lines.append(f"  ⚠️ Indeterminate      : {self.indeterminate_rules}")
        lines.append(f"{sep}")
        if not self.all_breaches():
            lines.append("  ✅ ALL RULES PASSED — Data contract satisfied.")
        else:
            lines.append("  Breaches:")
            for b in self.all_breaches():
                lines.append(f"    {b}")
        lines.append(f"{sep}")
        if self.failed:
            overall = "❌ FAILED"
        elif self.indeterminate_rules > 0:
            overall = "⚠️ INDETERMINATE"
        else:
            overall = "✅ PASSED"
        lines.append(f"  Overall verdict: {overall}")
        lines.append(f"{sep}\n")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
#  validate() — the main public entry point
# ─────────────────────────────────────────────────────────────────────────────
def validate(
    data: Any,
    rules: dict[str, dict[str, Any]],
    profile: Any = None,
    fail_on_error: bool = False,
) -> ValidationReport:
    """Validate data against a declarative rule contract."""
    if profile is None:
        import zedda as zd

        profile = zd.scan(data)

    file_name = getattr(profile, "file_name", "<unknown>")
    report = ValidationReport(file_name=file_name)

    col_by_name: dict[str, Any] = {}
    for col in profile.columns:
        col_by_name[col.name] = col

    total_rules = 0
    passed_rules = 0
    failed_rules = 0
    indeterminate_rules = 0
    any_critical_failure = False

    for col_name, col_rules in rules.items():
        breaches: list[RuleBreachDetail] = []
        rule_results: dict[str, RuleResult] = {}
        col_passed = True
        col_status = ValidationStatus.PASS
        col_profile = col_by_name.get(col_name)

        if col_profile is None:
            for rule_name in col_rules:
                total_rules += 1
                failed_rules += 1
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule=rule_name,
                        expected="column to exist",
                        actual="column not found in dataset",
                        severity="CRITICAL",
                        status=ValidationStatus.FAIL,
                        reason="Column not found in dataset",
                    )
                )
                rule_results[rule_name] = RuleResult(
                    evaluated=True,
                    status=ValidationStatus.FAIL,
                    reason="Column not found in dataset",
                )
                col_passed = False
                col_status = ValidationStatus.FAIL
                any_critical_failure = True
            report.columns.append(
                ColumnValidationResult(
                    column=col_name,
                    passed=col_passed,
                    breaches=breaches,
                    rule_results=rule_results,
                    status=col_status,
                )
            )
            continue

        total_count = getattr(
            col_profile, "total_count", getattr(profile, "num_rows", 0)
        )

        # 1. max_null_pct
        if "max_null_pct" in col_rules:
            total_rules += 1
            limit = float(col_rules["max_null_pct"])
            actual_pct = getattr(col_profile, "null_pct", None)
            if actual_pct is None:
                indeterminate_rules += 1
                col_passed = False
                if col_status != ValidationStatus.FAIL:
                    col_status = ValidationStatus.INDETERMINATE
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="max_null_pct",
                        expected=f"≤ {limit:.1f}%",
                        actual="null_pct unavailable",
                        severity="INDETERMINATE",
                        status=ValidationStatus.INDETERMINATE,
                        reason="Missing null_pct metric in profile",
                    )
                )
                rule_results["max_null_pct"] = RuleResult(
                    evaluated=False,
                    status=ValidationStatus.INDETERMINATE,
                    reason="Missing null_pct metric in profile",
                )
            elif actual_pct > limit:
                failed_rules += 1
                col_passed = False
                col_status = ValidationStatus.FAIL
                any_critical_failure = True
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="max_null_pct",
                        expected=f"≤ {limit:.1f}%",
                        actual=f"{actual_pct:.2f}%",
                        severity="CRITICAL",
                        status=ValidationStatus.FAIL,
                        reason=f"null_pct {actual_pct:.2f}% exceeds limit {limit:.1f}%",
                    )
                )
                rule_results["max_null_pct"] = RuleResult(
                    evaluated=True,
                    status=ValidationStatus.FAIL,
                    reason=f"null_pct {actual_pct:.2f}% exceeds limit {limit:.1f}%",
                )
            else:
                passed_rules += 1
                rule_results["max_null_pct"] = RuleResult(
                    evaluated=True,
                    status=ValidationStatus.PASS,
                )

        # 2. min
        if "min" in col_rules:
            total_rules += 1
            limit = float(col_rules["min"])
            actual_min = getattr(col_profile, "val_min", None)
            if actual_min is None:
                indeterminate_rules += 1
                col_passed = False
                if col_status != ValidationStatus.FAIL:
                    col_status = ValidationStatus.INDETERMINATE
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="min",
                        expected=f">= {limit}",
                        actual="val_min is None (insufficient numeric evidence)",
                        severity="INDETERMINATE",
                        status=ValidationStatus.INDETERMINATE,
                        reason="No minimum value available to evaluate min rule",
                    )
                )
                rule_results["min"] = RuleResult(
                    evaluated=False,
                    status=ValidationStatus.INDETERMINATE,
                    reason="No minimum value available to evaluate min rule",
                )
            elif actual_min < limit:
                failed_rules += 1
                col_passed = False
                col_status = ValidationStatus.FAIL
                any_critical_failure = True
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="min",
                        expected=f">= {limit}",
                        actual=str(actual_min),
                        severity="CRITICAL",
                        status=ValidationStatus.FAIL,
                        reason=f"min value {actual_min} < {limit}",
                    )
                )
                rule_results["min"] = RuleResult(
                    evaluated=True,
                    status=ValidationStatus.FAIL,
                    reason=f"min value {actual_min} < {limit}",
                )
            else:
                passed_rules += 1
                rule_results["min"] = RuleResult(
                    evaluated=True,
                    status=ValidationStatus.PASS,
                )

        # 3. max
        if "max" in col_rules:
            total_rules += 1
            limit = float(col_rules["max"])
            actual_max = getattr(col_profile, "val_max", None)
            if actual_max is None:
                indeterminate_rules += 1
                col_passed = False
                if col_status != ValidationStatus.FAIL:
                    col_status = ValidationStatus.INDETERMINATE
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="max",
                        expected=f"<= {limit}",
                        actual="val_max is None (insufficient numeric evidence)",
                        severity="INDETERMINATE",
                        status=ValidationStatus.INDETERMINATE,
                        reason="No maximum value available to evaluate max rule",
                    )
                )
                rule_results["max"] = RuleResult(
                    evaluated=False,
                    status=ValidationStatus.INDETERMINATE,
                    reason="No maximum value available to evaluate max rule",
                )
            elif actual_max > limit:
                failed_rules += 1
                col_passed = False
                col_status = ValidationStatus.FAIL
                any_critical_failure = True
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="max",
                        expected=f"<= {limit}",
                        actual=str(actual_max),
                        severity="CRITICAL",
                        status=ValidationStatus.FAIL,
                        reason=f"max value {actual_max} > {limit}",
                    )
                )
                rule_results["max"] = RuleResult(
                    evaluated=True,
                    status=ValidationStatus.FAIL,
                    reason=f"max value {actual_max} > {limit}",
                )
            else:
                passed_rules += 1
                rule_results["max"] = RuleResult(
                    evaluated=True,
                    status=ValidationStatus.PASS,
                )

        # 4. is_unique (Phase 6.2 Exact vs Approximate Uniqueness)
        if col_rules.get("is_unique"):
            total_rules += 1
            unique_exact = getattr(col_profile, "unique_exact", -1)
            unique_approx = getattr(col_profile, "unique_approx", None)
            exact_valid = getattr(col_profile, "exact_unique_valid", False)

            if exact_valid and unique_exact != -1:
                # Exact proof available
                if unique_exact == total_count:
                    passed_rules += 1
                    rule_results["is_unique"] = RuleResult(
                        evaluated=True,
                        status=ValidationStatus.PASS,
                    )
                else:
                    failed_rules += 1
                    col_passed = False
                    col_status = ValidationStatus.FAIL
                    any_critical_failure = True
                    breaches.append(
                        RuleBreachDetail(
                            column=col_name,
                            rule="is_unique",
                            expected=f"all {total_count} rows unique",
                            actual=f"{unique_exact} unique / {total_count} total",
                            severity="CRITICAL",
                            status=ValidationStatus.FAIL,
                            reason=f"Exact count {unique_exact} < total {total_count}",
                        )
                    )
                    rule_results["is_unique"] = RuleResult(
                        evaluated=True,
                        status=ValidationStatus.FAIL,
                        reason=f"Exact count {unique_exact} < total {total_count}",
                    )
            else:
                # Cardinality is approximate (HLL) or unverified — cannot guarantee exact uniqueness
                indeterminate_rules += 1
                col_passed = False
                if col_status != ValidationStatus.FAIL:
                    col_status = ValidationStatus.INDETERMINATE
                approx_str = (
                    f"~{int(unique_approx)}" if unique_approx is not None else "unknown"
                )
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="is_unique",
                        expected=f"exact proof of {total_count} unique rows",
                        actual=f"approximate estimate only ({approx_str} unique)",
                        severity="INDETERMINATE",
                        status=ValidationStatus.INDETERMINATE,
                        reason="Exact uniqueness proof unavailable (cardinality is approximate HLL estimate)",
                    )
                )
                rule_results["is_unique"] = RuleResult(
                    evaluated=False,
                    status=ValidationStatus.INDETERMINATE,
                    reason="Exact uniqueness proof unavailable (cardinality is approximate HLL estimate)",
                )

        # 5. allowed_values (Phase 6.1 Tri-State Evidence Check)
        if "allowed_values" in col_rules:
            total_rules += 1
            allowed = set(str(v) for v in col_rules["allowed_values"])
            top_values = getattr(col_profile, "top_values", [])
            distinct_values = getattr(col_profile, "distinct_values", [])
            distinct_overflowed = getattr(col_profile, "distinct_overflowed", False)
            unique_exact = getattr(col_profile, "unique_exact", -1)
            exact_valid = getattr(col_profile, "exact_unique_valid", False)

            observed_values: set[str] = set()
            is_complete = False

            if distinct_values and not distinct_overflowed:
                observed_values = set(str(v) for v in distinct_values)
                is_complete = True
            elif top_values:
                observed_values = set(str(v) for v in top_values)
                if (
                    exact_valid
                    and unique_exact != -1
                    and len(observed_values) >= unique_exact
                ) or (len(top_values) >= total_count):
                    is_complete = True

            if not observed_values:
                # No value evidence available in profile
                indeterminate_rules += 1
                col_passed = False
                if col_status != ValidationStatus.FAIL:
                    col_status = ValidationStatus.INDETERMINATE
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="allowed_values",
                        expected=f"values in {sorted(allowed)}",
                        actual="no value samples available in profile",
                        severity="INDETERMINATE",
                        status=ValidationStatus.INDETERMINATE,
                        reason="No value samples available to evaluate allowed_values",
                    )
                )
                rule_results["allowed_values"] = RuleResult(
                    evaluated=False,
                    status=ValidationStatus.INDETERMINATE,
                    reason="No value samples available to evaluate allowed_values",
                )
            else:
                illegal = observed_values - allowed
                if illegal:
                    failed_rules += 1
                    col_passed = False
                    col_status = ValidationStatus.FAIL
                    any_critical_failure = True
                    breaches.append(
                        RuleBreachDetail(
                            column=col_name,
                            rule="allowed_values",
                            expected=f"values in {sorted(allowed)}",
                            actual=f"found illegal values: {sorted(illegal)}",
                            severity="CRITICAL",
                            status=ValidationStatus.FAIL,
                            reason=f"Illegal values found: {sorted(illegal)}",
                        )
                    )
                    rule_results["allowed_values"] = RuleResult(
                        evaluated=True,
                        status=ValidationStatus.FAIL,
                        reason=f"Illegal values found: {sorted(illegal)}",
                        violating_row_sample=sorted(illegal),
                    )
                elif is_complete:
                    passed_rules += 1
                    rule_results["allowed_values"] = RuleResult(
                        evaluated=True,
                        status=ValidationStatus.PASS,
                    )
                else:
                    indeterminate_rules += 1
                    col_passed = False
                    if col_status != ValidationStatus.FAIL:
                        col_status = ValidationStatus.INDETERMINATE
                    breaches.append(
                        RuleBreachDetail(
                            column=col_name,
                            rule="allowed_values",
                            expected=f"all values in {sorted(allowed)}",
                            actual=f"sample verified ({len(observed_values)} values), but full distinct population not proven",
                            severity="INDETERMINATE",
                            status=ValidationStatus.INDETERMINATE,
                            reason="Sample values are allowed, but full distinct population was not completely examined",
                        )
                    )
                    rule_results["allowed_values"] = RuleResult(
                        evaluated=False,
                        status=ValidationStatus.INDETERMINATE,
                        reason="Sample values are allowed, but full distinct population was not completely examined",
                    )

        # 6. min_str_len
        if "min_str_len" in col_rules:
            total_rules += 1
            limit = int(col_rules["min_str_len"])
            actual_min_len = getattr(col_profile, "min_str_len", None)
            if actual_min_len is None:
                indeterminate_rules += 1
                col_passed = False
                if col_status != ValidationStatus.FAIL:
                    col_status = ValidationStatus.INDETERMINATE
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="min_str_len",
                        expected=f">= {limit} chars",
                        actual="min_str_len is None",
                        severity="INDETERMINATE",
                        status=ValidationStatus.INDETERMINATE,
                        reason="String length statistics unavailable",
                    )
                )
                rule_results["min_str_len"] = RuleResult(
                    evaluated=False,
                    status=ValidationStatus.INDETERMINATE,
                    reason="String length statistics unavailable",
                )
            elif actual_min_len < limit:
                failed_rules += 1
                col_passed = False
                if col_status != ValidationStatus.FAIL:
                    col_status = ValidationStatus.FAIL
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="min_str_len",
                        expected=f">= {limit} chars",
                        actual=f"{actual_min_len} chars",
                        severity="WARNING",
                        status=ValidationStatus.FAIL,
                        reason=f"min_str_len {actual_min_len} < {limit}",
                    )
                )
                rule_results["min_str_len"] = RuleResult(
                    evaluated=True,
                    status=ValidationStatus.FAIL,
                    reason=f"min_str_len {actual_min_len} < {limit}",
                )
            else:
                passed_rules += 1
                rule_results["min_str_len"] = RuleResult(
                    evaluated=True,
                    status=ValidationStatus.PASS,
                )

        # 7. max_str_len
        if "max_str_len" in col_rules:
            total_rules += 1
            limit = int(col_rules["max_str_len"])
            actual_max_len = getattr(col_profile, "max_str_len", None)
            if actual_max_len is None:
                indeterminate_rules += 1
                col_passed = False
                if col_status != ValidationStatus.FAIL:
                    col_status = ValidationStatus.INDETERMINATE
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="max_str_len",
                        expected=f"<= {limit} chars",
                        actual="max_str_len is None",
                        severity="INDETERMINATE",
                        status=ValidationStatus.INDETERMINATE,
                        reason="String length statistics unavailable",
                    )
                )
                rule_results["max_str_len"] = RuleResult(
                    evaluated=False,
                    status=ValidationStatus.INDETERMINATE,
                    reason="String length statistics unavailable",
                )
            elif actual_max_len > limit:
                failed_rules += 1
                col_passed = False
                if col_status != ValidationStatus.FAIL:
                    col_status = ValidationStatus.FAIL
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="max_str_len",
                        expected=f"<= {limit} chars",
                        actual=f"{actual_max_len} chars",
                        severity="WARNING",
                        status=ValidationStatus.FAIL,
                        reason=f"max_str_len {actual_max_len} > {limit}",
                    )
                )
                rule_results["max_str_len"] = RuleResult(
                    evaluated=True,
                    status=ValidationStatus.FAIL,
                    reason=f"max_str_len {actual_max_len} > {limit}",
                )
            else:
                passed_rules += 1
                rule_results["max_str_len"] = RuleResult(
                    evaluated=True,
                    status=ValidationStatus.PASS,
                )

        # 8. regex (Phase 6.1 Tri-State Evidence Check)
        if "regex" in col_rules:
            total_rules += 1
            pattern = col_rules["regex"]
            top_values = getattr(col_profile, "top_values", [])
            distinct_values = getattr(col_profile, "distinct_values", [])
            samples = distinct_values or top_values
            unique_exact = getattr(col_profile, "unique_exact", -1)
            exact_valid = getattr(col_profile, "exact_unique_valid", False)

            try:
                compiled = re.compile(pattern)
                if not samples:
                    indeterminate_rules += 1
                    col_passed = False
                    if col_status != ValidationStatus.FAIL:
                        col_status = ValidationStatus.INDETERMINATE
                    breaches.append(
                        RuleBreachDetail(
                            column=col_name,
                            rule="regex",
                            expected=f"all values match /{pattern}/",
                            actual="no value samples available in profile",
                            severity="INDETERMINATE",
                            status=ValidationStatus.INDETERMINATE,
                            reason="No value samples available to evaluate regex",
                        )
                    )
                    rule_results["regex"] = RuleResult(
                        evaluated=False,
                        status=ValidationStatus.INDETERMINATE,
                        reason="No value samples available to evaluate regex",
                    )
                else:
                    non_matching = [v for v in samples if not compiled.match(str(v))]
                    if non_matching:
                        failed_rules += 1
                        col_passed = False
                        col_status = ValidationStatus.FAIL
                        breaches.append(
                            RuleBreachDetail(
                                column=col_name,
                                rule="regex",
                                expected=f"all values match /{pattern}/",
                                actual=f"non-matching samples: {non_matching[:3]}",
                                severity="WARNING",
                                status=ValidationStatus.FAIL,
                                reason=f"Non-matching values found: {non_matching[:3]}",
                            )
                        )
                        rule_results["regex"] = RuleResult(
                            evaluated=True,
                            status=ValidationStatus.FAIL,
                            reason=f"Non-matching values found: {non_matching[:3]}",
                            violating_row_sample=non_matching[:3],
                        )
                    else:
                        is_complete = (
                            exact_valid
                            and unique_exact != -1
                            and len(samples) >= unique_exact
                        ) or (len(samples) >= total_count)
                        if is_complete:
                            passed_rules += 1
                            rule_results["regex"] = RuleResult(
                                evaluated=True,
                                status=ValidationStatus.PASS,
                            )
                        else:
                            indeterminate_rules += 1
                            col_passed = False
                            if col_status != ValidationStatus.FAIL:
                                col_status = ValidationStatus.INDETERMINATE
                            breaches.append(
                                RuleBreachDetail(
                                    column=col_name,
                                    rule="regex",
                                    expected=f"all values match /{pattern}/",
                                    actual=f"sample verified ({len(samples)} values), but full population not proven",
                                    severity="INDETERMINATE",
                                    status=ValidationStatus.INDETERMINATE,
                                    reason="Sample values matched regex, but full population was not completely examined",
                                )
                            )
                            rule_results["regex"] = RuleResult(
                                evaluated=False,
                                status=ValidationStatus.INDETERMINATE,
                                reason="Sample values matched regex, but full population was not completely examined",
                            )
            except re.error as e:
                failed_rules += 1
                col_passed = False
                col_status = ValidationStatus.FAIL
                any_critical_failure = True
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="regex",
                        expected="valid regex pattern",
                        actual=f"invalid regex: {e}",
                        severity="CRITICAL",
                        status=ValidationStatus.FAIL,
                        reason=f"Invalid regex pattern: {e}",
                    )
                )
                rule_results["regex"] = RuleResult(
                    evaluated=True,
                    status=ValidationStatus.FAIL,
                    reason=f"Invalid regex pattern: {e}",
                )

        report.columns.append(
            ColumnValidationResult(
                column=col_name,
                passed=col_passed,
                breaches=breaches,
                rule_results=rule_results,
                status=col_status,
            )
        )

    report.total_rules = total_rules
    report.passed_rules = passed_rules
    report.failed_rules = failed_rules
    report.indeterminate_rules = indeterminate_rules
    report.failed = any_critical_failure or (failed_rules > 0)

    if fail_on_error and (any_critical_failure or report.failed):
        print(repr(report), file=sys.stderr)
        sys.exit(1)

    return report
