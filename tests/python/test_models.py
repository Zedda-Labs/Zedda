import pytest
from zedda._models import (
    Metric,
    MetricStatus,
    Coverage,
    RuleResult,
    ValidationStatus,
    CleaningPlan,
    CleanExecution,
)


def test_metric_immutability():
    m = Metric(
        value=1.0,
        status=MetricStatus.EXACT,
        coverage=Coverage(rows_examined=10, rows_total=10),
        method="exact",
    )
    with pytest.raises((AttributeError, TypeError)):
        m.value = 2.0  # Frozen dataclass should raise error


def test_rule_result_evaluated_guard():
    # If evaluated is False, status must be INDETERMINATE
    r1 = RuleResult(evaluated=False, status=ValidationStatus.PASS)
    assert r1.status == ValidationStatus.INDETERMINATE
    assert r1.reason == "Rule was not evaluated"

    r2 = RuleResult(evaluated=False, status=ValidationStatus.FAIL, reason="Test")
    assert r2.status == ValidationStatus.INDETERMINATE
    assert r2.reason == "Test"


def test_cleaning_plan_defaults():
    cp = CleaningPlan(proposed_changes=[], generated_from="test")
    assert cp.dry_run is True
    assert cp.requires_approval is True
