import pytest
import pandas as pd
import zedda as zd


def test_warnings_basic():
    df = pd.DataFrame({"id": [1, 2, 3, 4], "val": [1, None, 3, 4]})
    zd.warnings(df)


def test_warnings_canonical_module():
    from zedda._warnings import warnings as _warnings_fn, collect_warnings as _collect_warnings_fn
    assert zd.warnings is _warnings_fn
    assert zd.collect_warnings is _collect_warnings_fn


def test_warnings_terminal_output(tmp_path):
    import io
    from contextlib import redirect_stdout

    df = pd.DataFrame(
        {
            "id": range(100),
            "mostly_null": [None] * 80 + [1.0] * 20,
            "constant": ["val"] * 100,
        }
    )
    p = tmp_path / "warn_data.csv"
    df.to_csv(p, index=False)

    f = io.StringIO()
    with redirect_stdout(f):
        zd.warnings(str(p), show_fixes=True)
    out = f.getvalue()

    assert "warnings mode" in out
    assert "CRITICAL" in out or "critical" in out
    assert "Copy-Paste Fix Block" in out


def test_collect_warnings_programmatic(tmp_path):
    df = pd.DataFrame(
        {
            "id": range(100),
            "mostly_null": [None] * 80 + [1.0] * 20,
            "constant": ["val"] * 100,
        }
    )
    p = tmp_path / "warn_data2.csv"
    df.to_csv(p, index=False)

    # From file path
    warns = zd.collect_warnings(str(p))
    assert isinstance(warns, list)
    assert len(warns) > 0
    assert all("severity" in w and "column" in w and "message" in w for w in warns)

    # From DatasetProfile
    profile = zd.scan(str(p))
    warns_profile = zd.collect_warnings(profile)
    assert isinstance(warns_profile, list)
    assert len(warns_profile) == len(warns)

