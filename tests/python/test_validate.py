import pandas as pd
import pytest

import zedda as zd


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
