import time
import pandas as pd
import zedda as zd


def test_performance_scan_50k_rows(tmp_path):
    """Performance regression test: 50K row CSV must profile within 5 seconds."""
    csv_file = tmp_path / "perf_50k.csv"

    # Generate 50K rows, 10 columns
    df = pd.DataFrame(
        {
            "id": list(range(50_000)),
            "cat": [
                "category_A",
                "category_B",
                "category_C",
                "category_D",
                "category_E",
            ]
            * 10_000,
            "num1": [float(i * 1.5) for i in range(50_000)],
            "num2": [int(i % 100) for i in range(50_000)],
            "flag": [bool(i % 2 == 0) for i in range(50_000)],
        }
    )
    df.to_csv(csv_file, index=False)

    t0 = time.perf_counter()
    profile = zd.scan(str(csv_file))
    elapsed = time.perf_counter() - t0

    assert profile.num_rows == 50_000
    assert profile.num_cols == 5
    # Generous ceiling to prevent false positives across varied hardware in CI
    assert elapsed < 5.0, f"Profiling 50K rows took {elapsed:.2f}s (expected < 5.0s)"
