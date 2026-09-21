import pytest
from pathlib import Path
import zedda as zd


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_warnings_mostly_null(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "mostly_null.csv"))
    warns = zd.collect_warnings(p)
    assert len(warns) > 0
    # Should flag high nulls
    for w in warns:
        assert w["severity"] == "critical"
        assert w["type"] == "high_nulls"


def test_warnings_duplicates(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "duplicates.csv"))
    warns = zd.collect_warnings(p)
    # The current warnings logic does NOT check for row duplicates (that's for merge/compare).
    # But let's check it runs.
    assert isinstance(warns, list)


def test_warnings_high_cardinality(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "high_cardinality.csv"))
    warns = zd.collect_warnings(p)
    types = [w["type"] for w in warns]
    assert "id_like_string" in types or "high_cardinality" in types


def test_warnings_constant():
    import pandas as pd

    df = pd.DataFrame({"const": [1, 1, 1, 1, 1]})
    p = zd.scan(df)
    warns = zd.collect_warnings(p)
    types = [w["type"] for w in warns]
    assert "constant" in types


def test_warnings_outlier():
    import pandas as pd

    df = pd.DataFrame({"outlier_col": [1, 2, 3, 4, 1000000]})
    p = zd.scan(df)
    warns = zd.collect_warnings(p)
    types = [w["type"] for w in warns]
    assert "outlier" in types


def test_warnings_id_like():
    import pandas as pd

    df = pd.DataFrame({"id_col": range(100)})
    p = zd.scan(df)
    warns = zd.collect_warnings(p)
    types = [w["type"] for w in warns]
    assert "id_like" in types


def test_warnings_all_good():
    import pandas as pd

    df = pd.DataFrame(
        {
            "clean_num": [10.5, 11.2, 12.1, 10.8, 11.5, 12.0],
            "clean_cat": ["A", "B", "A", "C", "B", "A"],
        }
    )
    p = zd.scan(df)
    warns = zd.collect_warnings(p)
    assert len(warns) == 0


def test_warnings_cli_api(fixtures_dir):
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        zd.warnings(str(fixtures_dir / "mostly_null.csv"))
    out = f.getvalue()
    assert "mostly_null" in out
