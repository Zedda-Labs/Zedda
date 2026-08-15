import pytest
import pandas as pd
import zedda as zd


def test_compare_csv(tmp_path):
    df1 = pd.DataFrame({"id": [1, 2], "val": [10.0, 20.0]})
    df2 = pd.DataFrame({"id": [1, 2], "val": [10.0, 30.0]})
    p1 = tmp_path / "1.csv"
    p2 = tmp_path / "2.csv"
    df1.to_csv(p1, index=False)
    df2.to_csv(p2, index=False)

    zd.compare(str(p1), str(p2))


def test_compare_dataframe():
    df1 = pd.DataFrame({"id": [1, 2], "val": [10.0, 20.0]})
    df2 = pd.DataFrame({"id": [1, 2], "val": [10.0, 30.0]})
    zd.compare(df1, df2)

def test_scientific_drift_metrics(tmp_path):
    import io
    from contextlib import redirect_stdout
    import numpy as np
    
    # Base dataset: normal distribution
    np.random.seed(42)
    df1 = pd.DataFrame({"score": np.random.normal(50, 10, 1000).astype(int)})
    # Drifted dataset: shifted and wider
    df2 = pd.DataFrame({"score": np.random.normal(60, 15, 1000).astype(int)})
    
    f = io.StringIO()
    with redirect_stdout(f):
        zd.compare(df1, df2)
    
    out = f.getvalue()
    
    # We should see SHIFT or DRIFT and PSI/KS/WD metrics
    assert "PSI:" in out
    assert "KS:" in out
    assert "WD:" in out
    assert ("DRIFT" in out or "SHIFT" in out)
