"""
benchmarks/bench_parquet.py — Benchmark Parquet profiling across Pandas, Polars, DuckDB, and Zedda.

Hardware-normalized: reports raw throughput (rows/sec) and normalized throughput (rows/sec/core).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

import zedda as zd
try:
    from .bench_hardware_info import HardwareInfo, get_hardware_info
    from .bench_csv import BenchmarkResult, _time_fn
except ImportError:
    from benchmarks.bench_hardware_info import HardwareInfo, get_hardware_info
    from benchmarks.bench_csv import BenchmarkResult, _time_fn


def run_parquet_benchmarks(
    parquet_path: str,
    runs: int = 5,
    hw_info: HardwareInfo | None = None,
) -> list[BenchmarkResult]:
    if hw_info is None:
        hw_info = get_hardware_info()

    p = zd.scan(parquet_path)
    num_rows = p.num_rows
    num_cols = p.num_cols
    results: list[BenchmarkResult] = []

    # 1. Zedda
    times = _time_fn(lambda: zd.scan(parquet_path), runs=runs)
    med = float(np.median(times))
    rps = (num_rows / (med / 1000.0)) if med > 0 else 0.0
    results.append(
        BenchmarkResult(
            engine="Zedda",
            workload="Parquet Zero-Copy Profile",
            num_rows=num_rows,
            num_cols=num_cols,
            median_time_ms=med,
            min_time_ms=float(np.min(times)),
            max_time_ms=float(np.max(times)),
            rows_per_sec=rps,
            rows_per_sec_per_core=rps / hw_info.physical_cores,
        )
    )

    # 2. Polars
    try:
        import polars as pl

        def _polars_run():
            df = pl.read_parquet(parquet_path)
            return df.describe()

        times = _time_fn(_polars_run, runs=runs)
        med = float(np.median(times))
        rps = (num_rows / (med / 1000.0)) if med > 0 else 0.0
        results.append(
            BenchmarkResult(
                engine="Polars",
                workload="Parquet Read + Describe",
                num_rows=num_rows,
                num_cols=num_cols,
                median_time_ms=med,
                min_time_ms=float(np.min(times)),
                max_time_ms=float(np.max(times)),
                rows_per_sec=rps,
                rows_per_sec_per_core=rps / hw_info.physical_cores,
            )
        )
    except ImportError:
        pass

    # 3. DuckDB
    try:
        import duckdb

        def _duckdb_run():
            escaped = parquet_path.replace("\\", "/")
            return duckdb.sql(f"SUMMARIZE SELECT * FROM read_parquet('{escaped}')").fetchall()

        times = _time_fn(_duckdb_run, runs=runs)
        med = float(np.median(times))
        rps = (num_rows / (med / 1000.0)) if med > 0 else 0.0
        results.append(
            BenchmarkResult(
                engine="DuckDB",
                workload="Parquet SUMMARIZE SQL",
                num_rows=num_rows,
                num_cols=num_cols,
                median_time_ms=med,
                min_time_ms=float(np.min(times)),
                max_time_ms=float(np.max(times)),
                rows_per_sec=rps,
                rows_per_sec_per_core=rps / hw_info.physical_cores,
            )
        )
    except ImportError:
        pass

    # 4. Pandas / PyArrow
    try:
        def _pandas_run():
            df = pd.read_parquet(parquet_path)
            return df.describe(include="all")

        times = _time_fn(_pandas_run, runs=runs)
        med = float(np.median(times))
        rps = (num_rows / (med / 1000.0)) if med > 0 else 0.0
        results.append(
            BenchmarkResult(
                engine="Pandas",
                workload="Parquet Read + Describe All",
                num_rows=num_rows,
                num_cols=num_cols,
                median_time_ms=med,
                min_time_ms=float(np.min(times)),
                max_time_ms=float(np.max(times)),
                rows_per_sec=rps,
                rows_per_sec_per_core=rps / hw_info.physical_cores,
            )
        )
    except Exception:
        pass

    return results


if __name__ == "__main__":
    csv_file = "benchmarks/bench_200k.csv"
    pq_file = "benchmarks/bench_200k.parquet"
    if not os.path.exists(pq_file) and os.path.exists(csv_file):
        print(f"Creating {pq_file} from {csv_file}...")
        df = pd.read_csv(csv_file)
        df.to_parquet(pq_file, index=False)

    if os.path.exists(pq_file):
        hw = get_hardware_info()
        print("Hardware:", hw.summary())
        print("\nRunning Parquet Benchmarks...")
        res = run_parquet_benchmarks(pq_file, runs=3, hw_info=hw)
        print(f"{'Engine':<10} | {'Median ms':<10} | {'Rows/sec':<12} | {'Rows/sec/core':<15} | {'Speedup vs Pandas':<18}")
        print("-" * 75)
        pandas_res = next((r for r in res if r.engine == "Pandas"), None)
        baseline = pandas_res.median_time_ms if pandas_res else None
        for r in res:
            speedup = f"{baseline / r.median_time_ms:.2f}x" if baseline else "N/A"
            print(f"{r.engine:<10} | {r.median_time_ms:<10.1f} | {int(r.rows_per_sec):<12,d} | {int(r.rows_per_sec_per_core):<15,d} | {speedup:<18}")
