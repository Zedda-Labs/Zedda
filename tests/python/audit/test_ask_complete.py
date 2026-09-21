import pytest
from pathlib import Path
import zedda as zd
from zedda._errors import ZeddaError


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_answer_offline_patterns(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "mostly_null.csv"))

    # Test built-in regex patterns in _ask.py
    ans = zd.answer_offline("which columns should I drop?", p)
    assert "col1" in ans or "col2" in ans or "col3" in ans or "drop" in ans.lower()

    ans2 = zd.answer_offline("how many rows are there?", p)
    assert "100" in ans2


def test_answer_offline_target(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "ml_classification.csv"))
    ans = zd.answer_offline("what is the target column?", p)
    assert "target" in ans.lower()


def test_answer_offline_time_series(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "datetime.csv"))
    ans = zd.answer_offline("is this time series?", p)
    assert "yes" in ans.lower() or "time" in ans.lower()


def test_ask_no_api_key_error(fixtures_dir):
    import os

    # Temporarily remove GROQ_API_KEY if it exists
    old_key = os.environ.get("GROQ_API_KEY")
    if "GROQ_API_KEY" in os.environ:
        del os.environ["GROQ_API_KEY"]

    try:
        with pytest.raises(ZeddaError, match="GROQ_API_KEY"):
            zd.ask(str(fixtures_dir / "tiny.csv"), "tell me about this data")
    finally:
        if old_key is not None:
            os.environ["GROQ_API_KEY"] = old_key


def test_ask_path_validation():
    with pytest.raises(ZeddaError):
        # ask should validate that the path actually exists before doing AI stuff
        zd.ask("does_not_exist.csv", "what is this?")
