import pytest
import pandas as pd
import zedda as zd


def test_validate_rules_pass():
    df = pd.DataFrame({"age": [20, 30, 40], "status": ["A", "B", "A"], "id": [1, 2, 3]})

    rules = {
        "age": {"min": 0, "max": 100},
        "status": {"allowed_values": ["A", "B", "C"]},
        "id": {"is_unique": True, "max_null_pct": 0.0},
    }

    report = zd.validate(df, rules=rules)
    assert report.passed
    assert report.failed_rules == 0


def test_validate_rules_fail():
    df = pd.DataFrame(
        {"age": [120, 30, 40], "status": ["A", "Z", "A"], "id": [1, 1, 3]}
    )

    rules = {
        "age": {"min": 0, "max": 100},
        "status": {"allowed_values": ["A", "B", "C"]},
        "id": {"is_unique": True, "max_null_pct": 0.0},
    }

    report = zd.validate(df, rules=rules)
    assert not report.passed
    assert report.failed_rules == 3


def test_validate_missing_column():
    df = pd.DataFrame({"age": [20]})
    rules = {"missing_col": {"min": 0}}
    report = zd.validate(df, rules=rules)
    assert not report.passed
    assert report.failed_rules == 1


def test_validate_regex():
    df = pd.DataFrame({"email": ["test@test.com", "bad-email", "ok@test.com"]})
    rules = {"email": {"regex": r"^[\w.+-]+@[\w-]+\.[\w.-]+$"}}
    report = zd.validate(df, rules=rules)
    assert not report.passed
    breaches = report.all_breaches()
    assert len(breaches) > 0
    assert breaches[0].column == "email"
