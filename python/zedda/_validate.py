r"""
zedda._validate — Enterprise Data Contracts & Rule-Based Validation Engine.

Phase 2 Feature: Declarative data quality contracts that can be embedded
in CI/CD pipelines, data ingestion checks, and production monitoring.

Design Goals:
  - Zero-dependency (only uses ZEDDA's existing C++ profiling engine)
  - Declarative YAML-friendly rule format
  - Enterprise-grade output: pass/fail SLA per column + overall verdict
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


# ─────────────────────────────────────────────────────────────────────────────
#  RuleBreachDetail — one specific rule failure on one column
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RuleBreachDetail:
    column: str
    rule: str
    expected: str
    actual: str
    severity: str  # "CRITICAL" | "WARNING"

    def __str__(self) -> str:
        icon = "🔴" if self.severity == "CRITICAL" else "🟡"
        return (
            f"{icon} [{self.severity}] Column '{self.column}' — {self.rule}: "
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

    @property
    def failed(self) -> bool:
        return not self.passed


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
    failed: bool = False
    file_name: str = "<unknown>"

    @property
    def passed(self) -> bool:
        return not self.failed

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
            f"{sep}",
        ]
        if not self.all_breaches():
            lines.append("  ✅ ALL RULES PASSED — Data contract satisfied.")
        else:
            lines.append("  Breaches:")
            for b in self.all_breaches():
                lines.append(f"    {b}")
        lines.append(f"{sep}")
        overall = "❌ FAILED" if self.failed else "✅ PASSED"
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
    any_critical_failure = False

    for col_name, col_rules in rules.items():
        breaches: list[RuleBreachDetail] = []
        col_passed = True
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
                    )
                )
                col_passed = False
                any_critical_failure = True
            report.columns.append(
                ColumnValidationResult(col_name, col_passed, breaches)
            )
            continue

        if "max_null_pct" in col_rules:
            total_rules += 1
            limit = float(col_rules["max_null_pct"])
            actual_pct = getattr(col_profile, "null_pct", 0.0)
            if actual_pct > limit:
                failed_rules += 1
                col_passed = False
                any_critical_failure = True
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="max_null_pct",
                        expected=f"≤ {limit:.1f}%",
                        actual=f"{actual_pct:.2f}%",
                        severity="CRITICAL",
                    )
                )
            else:
                passed_rules += 1

        if "min" in col_rules:
            total_rules += 1
            limit = float(col_rules["min"])
            actual_min = getattr(col_profile, "val_min", None)
            if actual_min is None or actual_min < limit:
                failed_rules += 1
                col_passed = False
                any_critical_failure = True
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="min",
                        expected=f">= {limit}",
                        actual=str(actual_min),
                        severity="CRITICAL",
                    )
                )
            else:
                passed_rules += 1

        if "max" in col_rules:
            total_rules += 1
            limit = float(col_rules["max"])
            actual_max = getattr(col_profile, "val_max", None)
            if actual_max is None or actual_max > limit:
                failed_rules += 1
                col_passed = False
                any_critical_failure = True
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="max",
                        expected=f"<= {limit}",
                        actual=str(actual_max),
                        severity="CRITICAL",
                    )
                )
            else:
                passed_rules += 1

        if col_rules.get("is_unique"):
            total_rules += 1
            total_count = getattr(col_profile, "total_count", 0)
            unique_exact = getattr(col_profile, "unique_exact", -1)
            unique_approx = getattr(col_profile, "unique_approx", None)
            exact_valid = getattr(col_profile, "exact_unique_valid", False)

            if exact_valid and unique_exact != -1:
                unique_count = unique_exact
                is_unique = unique_count == total_count
            elif unique_approx is not None:
                is_unique = unique_approx >= total_count * 0.99
                unique_count = int(unique_approx)
            else:
                is_unique = True
                unique_count = total_count

            if not is_unique:
                failed_rules += 1
                col_passed = False
                any_critical_failure = True
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="is_unique",
                        expected=f"all {total_count} rows unique",
                        actual=f"~{unique_count} unique / {total_count} total",
                        severity="CRITICAL",
                    )
                )
            else:
                passed_rules += 1

        if "allowed_values" in col_rules:
            total_rules += 1
            allowed = set(str(v) for v in col_rules["allowed_values"])
            top_values = getattr(col_profile, "top_values", [])
            if top_values:
                actual_values = set(str(v) for v in top_values)
                illegal = actual_values - allowed
                if illegal:
                    failed_rules += 1
                    col_passed = False
                    any_critical_failure = True
                    breaches.append(
                        RuleBreachDetail(
                            column=col_name,
                            rule="allowed_values",
                            expected=f"values in {sorted(allowed)}",
                            actual=f"found illegal values: {sorted(illegal)}",
                            severity="CRITICAL",
                        )
                    )
                else:
                    passed_rules += 1
            else:
                passed_rules += 1

        if "min_str_len" in col_rules:
            total_rules += 1
            limit = int(col_rules["min_str_len"])
            actual_min_len = getattr(col_profile, "min_str_len", None)
            if actual_min_len is not None and actual_min_len < limit:
                failed_rules += 1
                col_passed = False
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="min_str_len",
                        expected=f">= {limit} chars",
                        actual=f"{actual_min_len} chars",
                        severity="WARNING",
                    )
                )
            else:
                passed_rules += 1

        if "max_str_len" in col_rules:
            total_rules += 1
            limit = int(col_rules["max_str_len"])
            actual_max_len = getattr(col_profile, "max_str_len", None)
            if actual_max_len is not None and actual_max_len > limit:
                failed_rules += 1
                col_passed = False
                breaches.append(
                    RuleBreachDetail(
                        column=col_name,
                        rule="max_str_len",
                        expected=f"<= {limit} chars",
                        actual=f"{actual_max_len} chars",
                        severity="WARNING",
                    )
                )
            else:
                passed_rules += 1

        if "regex" in col_rules:
            total_rules += 1
            pattern = col_rules["regex"]
            top_values = getattr(col_profile, "top_values", [])
            if top_values:
                try:
                    compiled = re.compile(pattern)
                    non_matching = [v for v in top_values if not compiled.match(str(v))]
                    if non_matching:
                        failed_rules += 1
                        col_passed = False
                        breaches.append(
                            RuleBreachDetail(
                                column=col_name,
                                rule="regex",
                                expected=f"all values match /{pattern}/",
                                actual=f"non-matching samples: {non_matching[:3]}",
                                severity="WARNING",
                            )
                        )
                    else:
                        passed_rules += 1
                except re.error as e:
                    failed_rules += 1
                    col_passed = False
                    breaches.append(
                        RuleBreachDetail(
                            column=col_name,
                            rule="regex",
                            expected="valid regex pattern",
                            actual=f"invalid regex: {e}",
                            severity="CRITICAL",
                        )
                    )
            else:
                passed_rules += 1

        report.columns.append(ColumnValidationResult(col_name, col_passed, breaches))

    report.total_rules = total_rules
    report.passed_rules = passed_rules
    report.failed_rules = failed_rules
    report.failed = any_critical_failure

    if fail_on_error and any_critical_failure:
        print(repr(report), file=sys.stderr)
        sys.exit(1)

    return report
