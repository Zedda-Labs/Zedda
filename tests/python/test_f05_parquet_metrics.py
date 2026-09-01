import zedda as zd
import math


def test_f05_parquet_footer_metrics():
    # Use a small known parquet file, e.g. tests/data/titanic.parquet if it exists
    # Wait, we might not have a parquet version of titanic in tests/data.
    # We can create one using pandas for the test
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    import os

    df = pd.DataFrame({"A": [1.0, 2.0, None, 4.0, 5.0]})
    table = pa.Table.from_pandas(df)
    pq.write_table(table, "test_f05.parquet")

    try:
        p = zd.scan("test_f05.parquet")
        col_a = p.columns[0]

        # Verify canonical metrics have the EXACT status and match footer
        assert col_a.metrics["null_pct"].status == "EXACT"
        assert col_a.metrics["null_pct"].value == 20.0

        assert col_a.metrics["min"].status == "EXACT"
        assert col_a.metrics["min"].value == 1.0

        assert col_a.metrics["max"].status == "EXACT"
        assert col_a.metrics["max"].value == 5.0
    finally:
        os.remove("test_f05.parquet")
