import os
import io
from pathlib import Path
from contextlib import redirect_stdout
import pytest
import zedda as zd


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_profile_basic(fixtures_dir):
    """Test that profile() calls scan() and prints without crashing."""
    f = io.StringIO()
    with redirect_stdout(f):
        p = zd.profile(str(fixtures_dir / "tiny.csv"))

    out = f.getvalue()
    assert p.num_rows == 3
    assert p.num_cols == 3

    # Check that rich console output happened
    assert "tiny.csv" in out
    assert "id" in out
    assert "name" in out


def test_profile_determinism(fixtures_dir):
    """Test that profiling the same file twice produces identical output models."""
    f1 = io.StringIO()
    with redirect_stdout(f1):
        p1 = zd.profile(str(fixtures_dir / "normal_business.csv"))

    f2 = io.StringIO()
    with redirect_stdout(f2):
        p2 = zd.profile(str(fixtures_dir / "normal_business.csv"))

    assert p1.num_rows == p2.num_rows
    assert p1.num_cols == p2.num_cols

    for c1, c2 in zip(p1.columns, p2.columns, strict=False):
        assert c1.name == c2.name
        assert c1.type_str == c2.type_str
        assert c1.null_count == c2.null_count
        assert c1.unique_approx == c2.unique_approx
        assert c1.val_min == c2.val_min
        assert c1.val_max == c2.val_max


def test_profile_sample_size(fixtures_dir):
    f = io.StringIO()
    with redirect_stdout(f):
        p = zd.profile(str(fixtures_dir / "large.csv"), sample_size=1000)

    assert p.num_rows == 1000
    assert p.is_sampled
