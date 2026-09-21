import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import zedda as zd


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_compare_identical():
    df = pd.DataFrame({"id": [1, 2, 3], "val": [10.0, 20.0, 30.0]})
    # In interactive compare, it prints. We can capture output or use internal function.
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        zd.compare(df, df)
    out = f.getvalue()
    assert "DRIFT" not in out and "SHIFT" not in out


def test_compare_shifted():
    np.random.seed(42)
    df1 = pd.DataFrame({"val": np.random.normal(50, 10, 1000).astype(int)})
    df2 = pd.DataFrame({"val": np.random.normal(70, 10, 1000).astype(int)})
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        zd.compare(df1, df2)
    out = f.getvalue()
    assert "SHIFT" in out or "DRIFT" in out
    assert "PSI:" in out


def test_compare_schema_drift():
    df1 = pd.DataFrame({"id": [1, 2], "val1": [10.0, 20.0]})
    df2 = pd.DataFrame({"id": [1, 2], "val2": [10.0, 30.0]})
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        zd.compare(df1, df2)
    out = f.getvalue()
    assert "val1" in out
    assert "val2" in out


def test_compare_categorical():
    df1 = pd.DataFrame({"cat": ["A", "B", "A", "B", "A"]})
    df2 = pd.DataFrame({"cat": ["A", "B", "C", "D", "A"]})
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        zd.compare(df1, df2)
    out = f.getvalue()
    # It should mention new categories
    assert "C" in out or "D" in out or "NEW CATEGORIES" in out


def test_compare_type_change():
    df1 = pd.DataFrame({"col": [1, 2, 3]})
    df2 = pd.DataFrame({"col": ["a", "b", "c"]})
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        zd.compare(df1, df2)
    out = f.getvalue()
    assert "TYPE MISMATCH" in out or "int" in out and "str" in out


def test_compare_null_drift():
    df1 = pd.DataFrame({"col": [1.0, 2.0, 3.0, 4.0, 5.0]})
    df2 = pd.DataFrame({"col": [1.0, None, None, None, 5.0]})
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        zd.compare(df1, df2)
    out = f.getvalue()
    # Null drift should be flagged if there's a big change in nulls
    assert "SPIKE" in out or "null" in out.lower()
