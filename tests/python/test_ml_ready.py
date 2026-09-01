from pathlib import Path
import pytest
import pandas as pd
import zedda as zd


def test_ml_ready_basic():
    df = pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            "val": [10, 20, 30, 40, 50],
            "cat": ["A", "B", "A", "B", "A"],
        }
    )
    result = zd.ml_ready(df)
    assert result is None  # Since it returns None


def test_ml_ready_type_coercion():
    df = pd.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            "val": ["10", "20", "30a", "40", "50"],
        }
    )
    # Should not crash on type coercion (Task 2 fix)
    zd.ml_ready(df)


def test_ml_ready_canonical_module():
    from zedda._ml_ready import ml_ready as _ml_ready_fn

    assert zd.ml_ready is _ml_ready_fn


def test_ml_ready_with_target_and_output(tmp_path):
    import io
    from contextlib import redirect_stdout

    df = pd.DataFrame(
        {
            "id": range(50),
            "feature1": [1.0 if i % 2 == 0 else 2.0 for i in range(50)],
            "target": [0 if i % 2 == 0 else 1 for i in range(50)],
        }
    )
    p = tmp_path / "train.csv"
    df.to_csv(p, index=False)

    f = io.StringIO()
    with redirect_stdout(f):
        zd.ml_ready(str(p), target="target")
    out = f.getvalue()

    assert "ML Readiness Score" in out
    assert "Target Column" in out
    assert "Feature Verdict Table" in out
    assert "TARGET" in out


def test_persist_encoding_mapping(tmp_path):
    from zedda._ml_ready import persist_encoding_mapping
    import json

    mapping = {"category": {"A": 0, "B": 1, "C": 2}}
    out_file = tmp_path / "encoding_map.json"
    persisted = persist_encoding_mapping(mapping, out_file)

    assert Path(persisted).exists()
    with open(out_file, encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == mapping
