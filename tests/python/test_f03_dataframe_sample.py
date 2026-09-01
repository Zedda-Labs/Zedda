import pandas as pd
import zedda as zd


def test_f03_dataframe_sampling():
    df = pd.DataFrame({"A": range(15000)})

    # Full scan
    p_full = zd.scan(df)
    assert not getattr(p_full, "is_sampled", False)
    assert p_full.num_rows == 15000

    # Sampled scan
    p_sampled = zd.scan(df, sample_size=1000)
    assert getattr(p_sampled, "is_sampled", False)
    assert p_sampled.num_rows == 15000

    col_a = p_sampled.columns[0]
    metric = col_a.metrics.get("mean")
    assert metric is not None
    assert metric.coverage is not None
    assert metric.coverage.rows_total == 15000
    assert metric.coverage.rows_examined == 1000


def test_f03_default_dataframe_scan_is_not_sampled_by_adapter_default():
    df = pd.DataFrame({"A": range(5)})
    p = zd.scan(df)
    assert not getattr(p, "is_sampled", False)
    assert p.columns[0].metrics["unique"].status.value == "EXACT"
