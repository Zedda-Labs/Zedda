"""
benchmarks/bench_csv.py — Benchmark CSV profiling across Pandas, Polars, DuckDB, and Zedda.

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
except ImportError:
    from benchmarks.bench_hardware_info import HardwareInfo, get_hardware_info


@dataclass(frozen=True)
class BenchmarkResult:
    engine: str
    workload: str
    num_rows: int
    num_cols: int
    median_time_ms: float
    min_time_ms: float
    max_time_ms: float
    rows_per_sec: float
    rows_per_sec_per_core: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "workload": self.workload,
            "num_rows": self.num_rows,
            "num_cols": self.num_cols,
            "median_time_ms": round(self.median_time_ms, 2),
            "min_time_ms": round(self.min_time_ms, 2),
            "max_time_ms": round(self.max_time_ms, 2),
            "rows_per_sec": int(round(self.rows_per_sec)),
            "rows_per_sec_per_core": int(round(self.rows_per_sec_per_core)),
        }


def _time_fn(fn, runs: int = 5) -> list[float]:
    # Warmup
    try:
        fn()
    except Exception:
        pass
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    return times


def run_csv_benchmarks(
    csv_path: str,
    runs: int = 5,
    hw_info: HardwareInfo | None = None,
) -> list[BenchmarkResult]:
    if hw_info is None:
        hw_info = get_hardware_info()

    # Determine row/col count using Zedda quick scan
    p = zd.scan(csv_path)
    num_rows = p.num_rows
    num_cols = p.num_cols
    results: list[BenchmarkResult] = []

    # 1. Zedda
    times = _time_fn(lambda: zd.scan(csv_path), runs=runs)
    med = float(np.median(times))
    rps = (num_rows / (med / 1000.0)) if med > 0 else 0.0
    results.append(
        BenchmarkResult(
            engine="Zedda",
            workload="CSV Full Profile",
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
            df = pl.read_csv(csv_path)
            return df.describe()

        times = _time_fn(_polars_run, runs=runs)
        med = float(np.median(times))
        rps = (num_rows / (med / 1000.0)) if med > 0 else 0.0
        results.append(
            BenchmarkResult(
                engine="Polars",
                workload="CSV Read + Describe",
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
            escaped = csv_path.replace("\\", "/")
            return duckdb.sql(f"SUMMARIZE SELECT * FROM read_csv_auto('{escaped}')").fetchall()

        times = _time_fn(_duckdb_run, runs=runs)
        med = float(np.median(times))
        rps = (num_rows / (med / 1000.0)) if med > 0 else 0.0
        results.append(
            BenchmarkResult(
                engine="DuckDB",
                workload="CSV SUMMARIZE SQL",
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

    # 4. Pandas
    try:
        def _pandas_run():
            df = pd.read_csv(csv_path)
            return df.describe(include="all")

        times = _time_fn(_pandas_run, runs=runs)
        med = float(np.median(times))
        rps = (num_rows / (med / 1000.0)) if med > 0 else 0.0
        results.append(
            BenchmarkResult(
                engine="Pandas",
                workload="CSV Read + Describe All",
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
    if not os.path.exists(csv_file):
        print(f"File {csv_file} not found. Run profile_hotspot.py first.")
    else:
        hw = get_hardware_info()
        print("Hardware:", hw.summary())
        print("\nRunning CSV Benchmarks...")
        res = run_csv_benchmarks(csv_file, runs=3, hw_info=hw)
        print(f"{'Engine':<10} | {'Median ms':<10} | {'Rows/sec':<12} | {'Rows/sec/core':<15} | {'Speedup vs Pandas':<18}")
        print("-" * 75)
        pandas_res = next((r for r in res if r.engine == "Pandas"), None)
        baseline = pandas_res.median_time_ms if pandas_res else None
        for r in res:
            speedup = f"{baseline / r.median_time_ms:.2f}x" if baseline else "N/A"
            print(f"{r.engine:<10} | {r.median_time_ms:<10.1f} | {int(r.rows_per_sec):<12,d} | {int(r.rows_per_sec_per_core):<15,d} | {speedup:<18}")
