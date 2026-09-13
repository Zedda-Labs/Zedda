import time
import pandas as pd
import polars as pl
import numpy as np
import zedda as zd
import os


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


def run_benchmark():
    print("Generating data (1M rows)...")
    generate_data(1_000_000)

    print("\n--- CSV Benchmark ---")

    t0 = time.time()
    pd.read_csv("benchmark_data.csv").describe(include="all")
    print(f"Pandas read + describe: {time.time() - t0:.3f}s")

    t0 = time.time()
    pl.read_csv("benchmark_data.csv").describe()
    print(f"Polars read + describe: {time.time() - t0:.3f}s")

    t0 = time.time()
    zd.scan("benchmark_data.csv").profile()
    print(f"Zedda scan + profile: {time.time() - t0:.3f}s")

    print("\n--- Parquet Benchmark ---")

    t0 = time.time()
    pd.read_parquet("benchmark_data.parquet").describe(include="all")
    print(f"Pandas read + describe: {time.time() - t0:.3f}s")

    t0 = time.time()
    pl.read_parquet("benchmark_data.parquet").describe()
    print(f"Polars read + describe: {time.time() - t0:.3f}s")

    t0 = time.time()
    zd.scan("benchmark_data.parquet").profile()
    print(f"Zedda scan + profile: {time.time() - t0:.3f}s")

    os.remove("benchmark_data.csv")
    os.remove("benchmark_data.parquet")


if __name__ == "__main__":
    run_benchmark()
