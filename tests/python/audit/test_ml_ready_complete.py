import pytest
import pandas as pd
from pathlib import Path
import zedda as zd


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_ml_ready_clean_dataset():
    df = pd.DataFrame(
        {
            "feat1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "feat2": [0.5, 0.4, 0.3, 0.2, 0.1],
            "target": [0, 1, 0, 1, 0],
        }
    )
    # ml_ready() returns (score, report_dict)
    score, rpt = zd.ml_ready(df)
    assert score == 100
    assert len(rpt["issues"]) == 0


def test_ml_ready_dirty_dataset(fixtures_dir):
    score, rpt = zd.ml_ready(str(fixtures_dir / "mostly_null.csv"))
    assert score < 100
    assert len(rpt["issues"]) > 0


def test_ml_ready_consistency(fixtures_dir):
    score, rpt = zd.ml_ready(str(fixtures_dir / "high_cardinality.csv"))
    p = zd.scan(str(fixtures_dir / "high_cardinality.csv"))
    warns = zd.collect_warnings(p)

    # The issues found by ml_ready should correspond to some degree with warnings
    # E.g. high cardinality should be flagged in both
    warn_types = [w["type"] for w in warns]
    assert "id_like_string" in warn_types or "high_cardinality" in warn_types
    # check that ml_ready flagged the UUID column
    assert any("uuid" in issue["column"] for issue in rpt["issues"])


def test_ml_ready_drop_cols():
    df = pd.DataFrame(
        {
            "good": [1, 2, 3, 4, 5],
            "bad": [1, 1, 1, 1, 1],  # constant
            "bad2": [None, None, None, None, None],  # all null
        }
    )
    score, rpt = zd.ml_ready(df)
    # the drop_cols suggestion should include 'bad' and 'bad2'
    if "drop_cols" in rpt:
        assert "bad" in rpt["drop_cols"]
        assert "bad2" in rpt["drop_cols"]
