"""
benchmarks/bench_report.py — Format and export benchmark results.

Generates:
1. Markdown report table.
2. JSON export for CI and historical tracking.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .bench_csv import BenchmarkResult
    from .bench_hardware_info import HardwareInfo
except ImportError:
    from benchmarks.bench_csv import BenchmarkResult
    from benchmarks.bench_hardware_info import HardwareInfo


def format_markdown_report(
    hw_info: HardwareInfo,
    csv_results: list[BenchmarkResult],
    parquet_results: list[BenchmarkResult],
) -> str:
    lines = [
        "# Zedda Hardware-Normalized Benchmark Report",
        "",
        f"> **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> **Hardware:** {hw_info.summary()}",
        "",
        "## 1. Methodology",
        "",
        "- **Metric:** `Rows/sec/core` is normalized by physical CPU core count.",
        "- **Timing:** `time.perf_counter()`, median of multiple runs after warm-up.",
        "- **Profiling Scope:** Full summary profiling (null count, mean, min/max, distinct, histograms).",
        "",
        "## 2. CSV Benchmark Results",
        "",
        "| Engine | Workload | Median (ms) | Throughput (rows/s) | Normalized (rows/s/core) | vs Pandas |",
        "|--------|----------|-------------|---------------------|--------------------------|-----------|",
    ]

    pandas_csv = next((r for r in csv_results if r.engine == "Pandas"), None)
    baseline_csv = pandas_csv.median_time_ms if pandas_csv else None

    for r in csv_results:
        speedup = f"{baseline_csv / r.median_time_ms:.2f}x" if baseline_csv else "N/A"
        lines.append(
            f"| **{r.engine}** | {r.workload} | {r.median_time_ms:.1f} | "
            f"{int(r.rows_per_sec):,d} | **{int(r.rows_per_sec_per_core):,d}** | {speedup} |"
        )

    lines.extend([
        "",
        "## 3. Parquet Benchmark Results",
        "",
        "| Engine | Workload | Median (ms) | Throughput (rows/s) | Normalized (rows/s/core) | vs Pandas |",
        "|--------|----------|-------------|---------------------|--------------------------|-----------|",
    ])

    pandas_pq = next((r for r in parquet_results if r.engine == "Pandas"), None)
    baseline_pq = pandas_pq.median_time_ms if pandas_pq else None

    for r in parquet_results:
        speedup = f"{baseline_pq / r.median_time_ms:.2f}x" if baseline_pq else "N/A"
        lines.append(
            f"| **{r.engine}** | {r.workload} | {r.median_time_ms:.1f} | "
            f"{int(r.rows_per_sec):,d} | **{int(r.rows_per_sec_per_core):,d}** | {speedup} |"
        )

    lines.append("")
    return "\n".join(lines)


def export_json_report(
    path: str,
    hw_info: HardwareInfo,
    csv_results: list[BenchmarkResult],
    parquet_results: list[BenchmarkResult],
) -> None:
    data = {
        "timestamp": datetime.now().isoformat(),
        "hardware": hw_info.to_dict(),
        "csv": [r.to_dict() for r in csv_results],
        "parquet": [r.to_dict() for r in parquet_results],
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
