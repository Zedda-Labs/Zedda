import pytest
import zedda as zd
import string
import random
import pandas as pd


def generate_random_string(length):
    return "".join(
        random.choices(string.ascii_letters + string.digits + " ,.\n", k=length)
    )


def test_fuzz_scan_random_csv():
    """Fuzz testing scan() on randomly generated CSV strings (via dataframe) to ensure no crash."""
    for _ in range(10):
        # Generate a random dataframe
        df = pd.DataFrame(
            {
                "col1": [
                    generate_random_string(random.randint(0, 100)) for _ in range(50)
                ],
                "col2": [
                    random.random() if random.random() > 0.2 else None
                    for _ in range(50)
                ],
                "col3": [random.randint(-1000, 1000) for _ in range(50)],
            }
        )

        # Should not crash
        p = zd.scan(df)
        assert p.num_rows == 50
        assert p.num_cols == 3


def test_fuzz_validate_random_rules():
    """Fuzz testing validate() on random rules to ensure graceful error handling."""
    df = pd.DataFrame({"col1": [1, 2, 3], "col2": ["A", "B", "C"]})

    # Meaningless rules should either be ignored or cause a failure, but NOT crash
    rules = {
        "col1": {"min": -100, "max": 100, "foo": "bar"},
        "col2": {
            "allowed_values": ["A", "B", "C", "D"],
            "is_unique": True,
            "fake_rule": 42,
        },
        "col3": {"min": 0},  # Non-existent column
    }

    report = zd.validate(df, rules=rules)
    assert not report.passed
    assert report.failed_rules > 0  # At least col3 will fail


def test_invariant_large_string_hll():
    """Test HLL accuracy with large string column."""
    import uuid

    df = pd.DataFrame({"uuid": [str(uuid.uuid4()) for _ in range(10000)]})

    p = zd.scan(df)
    unique_est = p.columns[0].unique_approx

    # HLL should be accurate within ~5% for large counts, but can be a bit off
    assert 9000 < unique_est < 11000


def test_invariant_empty_dataframe():
    df = pd.DataFrame()
    with pytest.raises(zd.ZeddaError, match="File is empty|No columns"):
        zd.scan(df)
