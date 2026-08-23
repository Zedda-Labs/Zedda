import json
import pandas as pd
import zedda as zd
from zedda._models import DatasetProfile


def test_dataset_profile_to_dict_and_to_json(tmp_path):
    df = pd.DataFrame({"id": [1, 2, 3], "val": [10.5, 20.5, 30.5]})
    p_path = tmp_path / "data.csv"
    df.to_csv(p_path, index=False)

    profile = zd.scan(str(p_path))
    assert isinstance(profile, DatasetProfile)

    d = profile.to_dict()
    assert isinstance(d, dict)
    assert d["file_name"] in (str(p_path), p_path.name)
    assert d["num_rows"] == 3
    assert d["num_cols"] == 2
    assert "columns" in d
    assert len(d["columns"]) == 2

    # Check metric provenance in dict output
    col_val = next(c for c in d["columns"] if c["name"] == "val")
    assert "metrics" in col_val
    null_metric = col_val["metrics"]["null_pct"]
    assert "value" in null_metric
    assert "status" in null_metric
    assert "coverage" in null_metric
    assert "method" in null_metric

    json_str = profile.to_json(indent=2)
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["num_rows"] == 3
