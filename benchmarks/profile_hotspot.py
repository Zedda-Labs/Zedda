"""
benchmarks/profile_hotspot.py — Profile Python vs C++ overhead in Zedda scan.

Generates a test dataset (or uses an existing one) and profiles:
1. Pure C++ profile() execution time.
2. Python-side bridge and post-processing time (legacy_to_profile_result, _engine).
3. Detailed cProfile function-level breakdown.
"""

from __future__ import annotations

import cProfile
import os
import pstats
import time
from pathlib import Path
import numpy as np
import pandas as pd

import zedda as zd
from zedda import fasteda_core as _core


def generate_benchmark_csv(path: str, rows: int = 200_000) -> None:
    if os.path.exists(path):
        return
    print(f"Generating benchmark dataset with {rows:,} rows -> {path} ...")
    np.random.seed(42)
    df = pd.DataFrame(
        {
            "id": np.arange(rows, dtype=np.int64),
            "age": np.random.randint(18, 90, size=rows),
            "fare": np.random.exponential(scale=30.0, size=rows),
            "score": np.random.normal(loc=100.0, scale=15.0, size=rows),
            "city": np.random.choice(
                ["New York", "London", "Tokyo", "Paris", "Berlin", "Sydney"], size=rows
            ),
            "category": np.random.choice(
                ["Bronze", "Silver", "Gold", "Platinum"], size=rows
            ),
            "status": np.random.choice(
                ["active", "pending", "suspended", "cancelled"], size=rows
            ),
            "flag": np.random.choice([True, False], size=rows),
            "notes": np.random.choice(
                ["ok", "verified", "flagged", "reviewed", ""], size=rows
            ),
            "nullable_val": np.where(
                np.random.rand(rows) < 0.2, np.nan, np.random.randn(rows)
            ),
        }
    )
    df.to_csv(path, index=False)
    print(f"Dataset generated: {os.path.getsize(path) / (1024 * 1024):.2f} MB")


def profile_scan(csv_path: str) -> None:
    # 1. Measure pure C++ kernel
    times_cpp = []
    for _ in range(5):
        t0 = time.perf_counter()
        cpp_prof = _core.profile(
            csv_path, False, False, 1_000_000, False, ord(","), ord('"'), 0, "auto"
        )
        times_cpp.append((time.perf_counter() - t0) * 1000.0)
    median_cpp = float(np.median(times_cpp))

    # 2. Measure full zd.scan()
    times_full = []
    for _ in range(5):
        t0 = time.perf_counter()
        prof = zd.scan(csv_path)
        times_full.append((time.perf_counter() - t0) * 1000.0)
    median_full = float(np.median(times_full))

    python_overhead = median_full - median_cpp
    overhead_pct = (python_overhead / median_full) * 100.0 if median_full > 0 else 0.0

    print("=" * 60)
    print("ZEDDA SCAN PROFILE BREAKDOWN")
    print("=" * 60)
    print(
        f"Dataset:            {csv_path} ({os.path.getsize(csv_path) / (1024 * 1024):.2f} MB)"
    )
    print(f"Pure C++ kernel:    {median_cpp:.2f} ms (median of 5)")
    print(f"Full zd.scan():     {median_full:.2f} ms (median of 5)")
    print(
        f"Python bridge time: {python_overhead:.2f} ms ({overhead_pct:.1f}% of total time)"
    )
    print("=" * 60)

    # 3. Detailed cProfile on full zd.scan()
    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(10):
        zd.scan(csv_path)
    profiler.disable()

    print("\n--- TOP 20 CPROFILE HOTSPOTS (by cumulative time) ---")
    stats = pstats.Stats(profiler)
    stats.strip_dirs()
    stats.sort_stats("cumtime")
    stats.print_stats(20)


if __name__ == "__main__":
    bench_dir = Path("benchmarks")
    bench_dir.mkdir(exist_ok=True)
    csv_file = str(bench_dir / "bench_200k.csv")
    generate_benchmark_csv(csv_file, rows=200_000)
    profile_scan(csv_file)
