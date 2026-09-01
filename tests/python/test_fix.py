import io
from contextlib import redirect_stdout
import pandas as pd
import pytest
import zedda as zd
from zedda._fix import fix as _fix_fn


def test_fix_canonical_module():
    assert zd.fix is _fix_fn


def test_fix_apply_false(tmp_path):
    df = pd.DataFrame(
        {
            "id": range(100),
            "val": [1.0 if i % 2 == 0 else None for i in range(100)],
            "category": [f"cat_{i}" for i in range(100)],
        }
    )
    p = tmp_path / "dirty.csv"
    df.to_csv(p, index=False)

    f = io.StringIO()
    with redirect_stdout(f):
        res = zd.fix(str(p), apply=False)
    assert res is None
    out = f.getvalue()
    assert "zd.fix()" in out
    assert "MISSING VALUES" in out or "ID COLUMNS" in out or "ENCODING" in out


def test_fix_apply_true(tmp_path):
    df = pd.DataFrame(
        {
            "id": range(100),
            "val": [1.0 if i % 2 == 0 else None for i in range(100)],
            "category": [f"cat_{i % 5}" for i in range(100)],
        }
    )
    p = tmp_path / "dirty.csv"
    df.to_csv(p, index=False)

    clean_df = zd.fix(str(p), apply=True)
    assert isinstance(clean_df, pd.DataFrame)
    # The id column with 100% unique ints should have been dropped
    assert "id" not in clean_df.columns
    # The val column nulls should be filled
    assert clean_df["val"].isna().sum() == 0
