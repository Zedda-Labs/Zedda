"""
benchmarks/bench_suite.py — Main runner for the hardware-normalized benchmark suite.

Usage:
    python -m benchmarks.bench_suite [--rows 200000] [--runs 5]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from benchmarks.bench_hardware_info import get_hardware_info
    from benchmarks.bench_csv import run_csv_benchmarks
    from benchmarks.bench_parquet import run_parquet_benchmarks
    from benchmarks.bench_report import export_json_report, format_markdown_report
    from benchmarks.profile_hotspot import generate_benchmark_csv
else:
    from .bench_hardware_info import get_hardware_info
    from .bench_csv import run_csv_benchmarks
    from .bench_parquet import run_parquet_benchmarks
    from .bench_report import export_json_report, format_markdown_report
    from .profile_hotspot import generate_benchmark_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Zedda hardware-normalized benchmark suite")
    parser.add_argument("--rows", type=int, default=200_000, help="Row count for benchmark files (default: 200,000)")
    parser.add_argument("--runs", type=int, default=3, help="Number of benchmark runs (default: 3)")
    parser.add_argument("--output-md", type=str, default="benchmarks/report.md", help="Path for markdown report")
    parser.add_argument("--output-json", type=str, default="benchmarks/report.json", help="Path for JSON report")
    args = parser.parse_args()

    bench_dir = Path("benchmarks")
    bench_dir.mkdir(exist_ok=True)
    csv_file = str(bench_dir / f"bench_{args.rows // 1000}k.csv")
    pq_file = str(bench_dir / f"bench_{args.rows // 1000}k.parquet")

    # Generate test files if needed
    if not os.path.exists(csv_file):
        generate_benchmark_csv(csv_file, rows=args.rows)
    if not os.path.exists(pq_file):
        print(f"Generating Parquet file -> {pq_file} ...")
        df = pd.read_csv(csv_file)
        df.to_parquet(pq_file, index=False)

    hw = get_hardware_info()
    print("=" * 70)
    print("ZEDDA HARDWARE-NORMALIZED BENCHMARK SUITE")
    print("=" * 70)
    print(f"System:  {hw.summary()}")
    print(f"Dataset: {csv_file} ({args.rows:,} rows, {args.runs} runs per engine)")
    print("=" * 70)

    print("\n[1/2] Running CSV benchmarks...")
    csv_results = run_csv_benchmarks(csv_file, runs=args.runs, hw_info=hw)

    print("\n[2/2] Running Parquet benchmarks...")
    pq_results = run_parquet_benchmarks(pq_file, runs=args.runs, hw_info=hw)

    # Format and save report
    md_report = format_markdown_report(hw, csv_results, pq_results)
    export_json_report(args.output_json, hw, csv_results, pq_results)

    with open(args.output_md, "w", encoding="utf-8") as f:
        f.write(md_report)

    print("\n" + md_report)
    print(f"Reports saved to {args.output_md} and {args.output_json}")


if __name__ == "__main__":
    main()
