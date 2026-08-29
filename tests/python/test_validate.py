from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

import zedda as zd
from zedda._models import (
    ColumnProfile,
    Coverage,
    DatasetProfile,
    Metric,
    MetricStatus,
    ValidationStatus,
)


@pytest.fixture
def enterprise_df():
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            "status": ["active", "active", "pending", "active", "inactive"],
            "age": [25, 30, 45, 12, 105],
            "email": ["a@b.com", "b@b.com", "c@b.com", "d@b.com", "bad-email"],
            "score": [99.5, 88.0, 75.5, 90.0, None],
        }
    )


def test_validate_passes(enterprise_df):
    rules = {
        "id": {"is_unique": True, "max_null_pct": 0.0},
        "status": {"allowed_values": ["active", "inactive", "pending"]},
        "age": {"min": 0, "max": 120},
    }
    report = zd.validate(enterprise_df, rules=rules)
    assert report.passed
    assert not report.failed
    assert report.total_rules == 5
    assert report.passed_rules == 5
    assert report.failed_rules == 0
    assert len(report.all_breaches()) == 0


def test_validate_fails(enterprise_df):
    rules = {
        "age": {"max": 100},  # Fails (max is 105)
        "email": {"regex": r"^[\w.+-]+@[\w-]+\.[\w.-]+$"},  # Fails ("bad-email")
        "score": {"max_null_pct": 0.0},  # Fails (has 1 null)
        "id": {"min": 0},  # Passes
    }
    report = zd.validate(enterprise_df, rules=rules)
    assert not report.passed
    assert report.failed
    assert report.total_rules == 4
    assert report.failed_rules == 3

    breaches = report.all_breaches()
    assert len(breaches) == 3

    col_failures = [b.column for b in breaches]
    assert "age" in col_failures
    assert "email" in col_failures
    assert "score" in col_failures


def test_validate_missing_column(enterprise_df):
    rules = {
        "non_existent": {"is_unique": True},
    }
    report = zd.validate(enterprise_df, rules=rules)
    assert report.failed
    assert report.failed_rules == 1
    assert "not found" in report.all_breaches()[0].actual


def _profile_dataframe(df, sample_size=None):
    return zd.scan(df, sample_size=sample_size)


def test_complete_dataframe_unique_pass():
    df = pd.DataFrame({"id": [1, 2, 3]})
    report = zd.validate(
        None,
        rules={"id": {"is_unique": True}},
        profile=_profile_dataframe(df),
    )
    assert report.passed
    assert report.passed_rules == 1


def test_complete_dataframe_unique_fail():
    df = pd.DataFrame({"id": [1, 2, 2]})
    report = zd.validate(
        None,
        rules={"id": {"is_unique": True}},
        profile=_profile_dataframe(df),
    )
    assert report.failed
    assert report.failed_rules == 1
    assert report.columns[0].rule_results["is_unique"].status == ValidationStatus.FAIL


def test_complete_dataframe_allowed_values_pass():
    df = pd.DataFrame({"status": ["active", "inactive", "active"]})
    report = zd.validate(
        None,
        rules={"status": {"allowed_values": ["active", "inactive"]}},
        profile=_profile_dataframe(df),
    )
    assert report.passed
    assert report.passed_rules == 1


def test_complete_dataframe_allowed_values_fail():
    df = pd.DataFrame({"status": ["active", "blocked"]})
    report = zd.validate(
        None,
        rules={"status": {"allowed_values": ["active", "inactive"]}},
        profile=_profile_dataframe(df),
    )
    assert report.failed
    assert report.failed_rules == 1
    assert (
        report.columns[0].rule_results["allowed_values"].status == ValidationStatus.FAIL
    )


def test_sampled_dataframe_unique_is_indeterminate():
    df = pd.DataFrame({"id": range(200)})
    report = zd.validate(
        None,
        rules={"id": {"is_unique": True}},
        profile=_profile_dataframe(df, sample_size=20),
    )
    assert report.indeterminate
    assert report.indeterminate_rules == 1


def test_sampled_dataframe_allowed_values_is_indeterminate():
    df = pd.DataFrame({"status": ["active", "inactive"] * 100})
    report = zd.validate(
        None,
        rules={"status": {"allowed_values": ["active", "inactive"]}},
        profile=_profile_dataframe(df, sample_size=20),
    )
    assert report.indeterminate
    assert report.indeterminate_rules == 1


def test_complete_dataframe_regex_validation():
    passing = pd.DataFrame({"email": ["a@example.com", "b@example.com"]})
    passing_report = zd.validate(
        None,
        rules={"email": {"regex": r"^[\w.+-]+@[\w-]+\.[\w.-]+$"}},
        profile=_profile_dataframe(passing),
    )
    assert passing_report.passed

    failing = pd.DataFrame({"email": ["a@example.com", "not-an-email"]})
    failing_report = zd.validate(
        None,
        rules={"email": {"regex": r"^[\w.+-]+@[\w-]+\.[\w.-]+$"}},
        profile=_profile_dataframe(failing),
    )
    assert failing_report.failed
    assert failing_report.failed_rules == 1


def make_col_profile(
    name: str,
    type_str: str,
    total_count: int = 100,
    null_pct: float = 0.0,
    unique_val: Any = None,
    unique_status: MetricStatus = MetricStatus.APPROXIMATE,
    val_min: Any = None,
    val_max: Any = None,
    min_len: Any = None,
    max_len: Any = None,
    top_values: list[Any] | None = None,
    distinct_values: list[Any] | None = None,
    distinct_overflowed: bool = False,
) -> ColumnProfile:
    cov = Coverage(rows_examined=total_count, rows_total=total_count)
    metrics: dict[str, Metric] = {
        "null_pct": Metric(
            value=null_pct,
            status=MetricStatus.EXACT,
            coverage=cov,
            method="exact",
        ),
    }
    if unique_val is not None:
        metrics["unique"] = Metric(
            value=unique_val,
            status=unique_status,
            coverage=cov,
            method="exact" if unique_status == MetricStatus.EXACT else "HLL",
        )
    if val_min is not None:
        metrics["min"] = Metric(
            value=val_min,
            status=MetricStatus.EXACT,
            coverage=cov,
            method="exact",
        )
    if val_max is not None:
        metrics["max"] = Metric(
            value=val_max,
            status=MetricStatus.EXACT,
            coverage=cov,
            method="exact",
        )
    if min_len is not None:
        metrics["min_len"] = Metric(
            value=min_len,
            status=MetricStatus.EXACT,
            coverage=cov,
            method="exact",
        )
    if max_len is not None:
        metrics["max_len"] = Metric(
            value=max_len,
            status=MetricStatus.EXACT,
            coverage=cov,
            method="exact",
        )

    return ColumnProfile(
        name=name,
        type_str=type_str,
        metrics=metrics,
        top_values=top_values or [],
        distinct_values_val=distinct_values or [],
        distinct_overflowed_val=distinct_overflowed,
    )


def test_validate_exact_vs_approximate_uniqueness():
    """Phase 6.2: is_unique requires exact proof; approximate/HLL returns INDETERMINATE."""
    # Synthetic profile with approximate uniqueness only (HLL estimate)
    approx_col = make_col_profile(
        name="user_id",
        type_str="int",
        total_count=100,
        unique_val=100.0,
        unique_status=MetricStatus.APPROXIMATE,
    )
    prof = DatasetProfile(
        file_name="simulated.csv",
        num_rows=100,
        num_cols=1,
        columns=[approx_col],
    )

    report = zd.validate(None, rules={"user_id": {"is_unique": True}}, profile=prof)
    assert not report.passed
    assert not report.failed
    assert report.indeterminate
    assert report.indeterminate_rules == 1
    assert report.passed_rules == 0
    assert report.failed_rules == 0

    col_res = report.columns[0]
    assert col_res.status == ValidationStatus.INDETERMINATE
    assert "is_unique" in col_res.rule_results
    assert not col_res.rule_results["is_unique"].evaluated
    assert col_res.rule_results["is_unique"].status == ValidationStatus.INDETERMINATE


def test_validate_exact_uniqueness_pass_and_fail():
    """Phase 6.2: exact uniqueness PASS when unique_exact == total_count, FAIL when less."""
    # Exact unique pass
    pass_col = make_col_profile(
        name="id_pass",
        type_str="int",
        total_count=50,
        unique_val=50,
        unique_status=MetricStatus.EXACT,
    )
    # Exact unique fail (duplicates exist)
    fail_col = make_col_profile(
        name="id_fail",
        type_str="int",
        total_count=50,
        unique_val=48,
        unique_status=MetricStatus.EXACT,
    )
    prof = DatasetProfile(
        file_name="simulated.csv",
        num_rows=50,
        num_cols=2,
        columns=[pass_col, fail_col],
    )

    report = zd.validate(
        None,
        rules={
            "id_pass": {"is_unique": True},
            "id_fail": {"is_unique": True},
        },
        profile=prof,
    )
    assert report.failed
    assert report.passed_rules == 1
    assert report.failed_rules == 1
    assert report.columns[0].rule_results["is_unique"].status == ValidationStatus.PASS
    assert report.columns[1].rule_results["is_unique"].status == ValidationStatus.FAIL


def test_validate_insufficient_evidence_indeterminate():
    """Phase 6.1: missing evidence returns INDETERMINATE instead of false PASS."""
    # Column with no top_values, no distinct_values, no min/max
    sparse_col = make_col_profile(
        name="category",
        type_str="str",
        total_count=100,
        top_values=[],
        distinct_values=[],
        val_min=None,
        val_max=None,
        min_len=None,
        max_len=None,
    )
    prof = DatasetProfile(
        file_name="sparse.csv",
        num_rows=100,
        num_cols=1,
        columns=[sparse_col],
    )

    report = zd.validate(
        None,
        rules={
            "category": {
                "allowed_values": ["A", "B"],
                "regex": r"^[A-Z]$",
                "min": 10,
                "max": 50,
                "min_str_len": 1,
                "max_str_len": 5,
            }
        },
        profile=prof,
    )

    assert not report.passed
    assert not report.failed
    assert report.indeterminate
    assert report.indeterminate_rules == 6
    assert report.passed_rules == 0
    assert report.failed_rules == 0

    col_res = report.columns[0]
    for rule_name in [
        "allowed_values",
        "regex",
        "min",
        "max",
        "min_str_len",
        "max_str_len",
    ]:
        rr = col_res.rule_results[rule_name]
        assert not rr.evaluated
        assert rr.status == ValidationStatus.INDETERMINATE


def test_validate_allowed_values_partial_sample_vs_complete():
    """Phase 6.1: partial top_values sample returns INDETERMINATE, complete returns PASS."""
    # Partial sample: 2 unique seen, but total rows = 100 and unique is approximate
    partial_col = make_col_profile(
        name="status_partial",
        type_str="str",
        total_count=100,
        unique_val=50,
        unique_status=MetricStatus.APPROXIMATE,
        top_values=["active", "pending"],
        distinct_values=[],
    )
    # Complete: all 2 unique values confirmed by distinct_values with no overflow
    complete_col = make_col_profile(
        name="status_complete",
        type_str="str",
        total_count=100,
        unique_val=2,
        unique_status=MetricStatus.EXACT,
        distinct_values=["active", "pending"],
        distinct_overflowed=False,
    )
    prof = DatasetProfile(
        file_name="status.csv",
        num_rows=100,
        num_cols=2,
        columns=[partial_col, complete_col],
    )

    report = zd.validate(
        None,
        rules={
            "status_partial": {"allowed_values": ["active", "pending"]},
            "status_complete": {"allowed_values": ["active", "pending"]},
        },
        profile=prof,
    )

    assert report.indeterminate_rules == 1
    assert report.passed_rules == 1
    assert (
        report.columns[0].rule_results["allowed_values"].status
        == ValidationStatus.INDETERMINATE
    )
    assert (
        report.columns[1].rule_results["allowed_values"].status == ValidationStatus.PASS
    )
