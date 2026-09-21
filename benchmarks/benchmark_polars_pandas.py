"""
Benchmark comparison: Zedda vs Polars vs Pandas.

Fairness Disclosures:
- Workload: Each library reads 1M rows (CSV/Parquet) and computes summary statistics.
- Metrics: Pandas/Polars compute .describe() while Zedda computes a streaming profile.
- Timings: 1 warmup run followed by 3 repetitions; median time is reported.
- Environment: System / CPU metadata logged for transparency.
"""

import os
import platform
import time
import numpy as np
import pandas as pd
import polars as pl
import zedda as zd


def generate_data(rows=1000000):
    df = pd.DataFrame(
        {
            "id": np.arange(rows),
            "value": np.random.randn(rows),
            "category": np.random.choice(["A", "B", "C", "D"], rows),
            "flag": np.random.choice([True, False], rows),
        }
    )
    df.to_csv("benchmark_data.csv", index=False)
    df.to_parquet("benchmark_data.parquet")


def measure(func, reps=3):
    # Warmup
    func()
    times = []
    for _ in range(reps):
        t0 = time.perf_counter()
        func()
        times.append(time.perf_counter() - t0)
    return float(np.median(times))


def run_benchmark():
    print(
        f"Platform: {platform.platform()} | Processor: {platform.processor()} | Cores: {os.cpu_count()}"
    )
    print("Generating data (1M rows)...")
    generate_data(1_000_000)

    try:
        print("\n--- CSV Benchmark (Median of 3 runs) ---")
        t_pd_csv = measure(
            lambda: pd.read_csv("benchmark_data.csv").describe(include="all")
        )
        print(f"Pandas read_csv + describe: {t_pd_csv:.3f}s")

        t_pl_csv = measure(lambda: pl.read_csv("benchmark_data.csv").describe())
        print(f"Polars read_csv + describe: {t_pl_csv:.3f}s")

        t_zd_csv = measure(lambda: zd.scan("benchmark_data.csv"))
        print(f"Zedda scan (CSV):          {t_zd_csv:.3f}s")

        print("\n--- Parquet Benchmark (Median of 3 runs) ---")
        t_pd_pq = measure(
            lambda: pd.read_parquet("benchmark_data.parquet").describe(include="all")
        )
        print(f"Pandas read_parquet + describe: {t_pd_pq:.3f}s")

        t_pl_pq = measure(lambda: pl.read_parquet("benchmark_data.parquet").describe())
        print(f"Polars read_parquet + describe: {t_pl_pq:.3f}s")

        t_zd_pq = measure(lambda: zd.scan("benchmark_data.parquet"))
        print(f"Zedda scan (Parquet):          {t_zd_pq:.3f}s")
    finally:
        if os.path.exists("benchmark_data.csv"):
            os.remove("benchmark_data.csv")
        if os.path.exists("benchmark_data.parquet"):
            os.remove("benchmark_data.parquet")


if __name__ == "__main__":
    run_benchmark()
