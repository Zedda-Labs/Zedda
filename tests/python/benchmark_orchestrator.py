import os
import sys
import time
import subprocess
import re
import statistics


# 1. Dataset Generation
def generate_dataset(rows, path):
    print(f"Generating {rows} rows -> {path}...")
    import pandas as pd
    import numpy as np

    if os.path.exists(path):
        print("  Already exists, skipping.")
        return

    np.random.seed(42)
    chunk_size = min(rows, 1000000)

    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "numeric_col,string_col,high_cardinality_string,missing_col,mixed_col\n"
        )

        for i in range(0, rows, chunk_size):
            size = min(chunk_size, rows - i)
            num = np.random.randn(size)
            str_col = np.random.choice(["A", "B", "C", "D", "E"], size)
            hc_str = [f"ID_{j}" for j in range(i, i + size)]
            miss = np.random.randn(size)
            miss[np.random.rand(size) < 0.5] = np.nan
            mixed = np.random.choice([1, 2, "three", "four", 5.5], size)

            df = pd.DataFrame(
                {
                    "numeric_col": num,
                    "string_col": str_col,
                    "high_cardinality_string": hc_str,
                    "missing_col": miss,
                    "mixed_col": mixed,
                }
            )
            df.to_csv(f, header=False, index=False, na_rep="")
    print("  Done.")


def parse_output(stdout, stderr):
    # Parse Python output
    total_time = 0.0
    peak_mb = 0.0
    base_mb = 0.0
    for line in stdout.splitlines():
        if line.startswith("__BENCH_TOTAL_TIME__:"):
            total_time = float(line.split(":")[1])
        if line.startswith("__BENCH_PEAK_MB__:"):
            peak_mb = float(line.split(":")[1])
        if line.startswith("__BENCH_BASE_MB__:"):
            base_mb = float(line.split(":")[1])

    # Parse C++ stderr
    # [zedda info] Profiler timing: 4 threads processed chunks in 14.2 ms | Merge took 2.3 ms
    engine_time = 0.0
    merge_time = 0.0
    for line in stderr.splitlines():
        m = re.search(
            r"processed chunks in ([\d\.]+) ms \| Merge took ([\d\.]+) ms", line
        )
        if m:
            engine_time = float(m.group(1)) / 1000.0
            merge_time = float(m.group(2)) / 1000.0
            break

    return total_time, engine_time + merge_time, peak_mb, base_mb


def run_benchmark(dataset_path, rows_name, iterations=3, threads=4):
    print(f"\n--- Benchmarking {rows_name} ---")

    total_times = []
    engine_times = []
    peak_mbs = []

    for i in range(iterations):
        cmd = [
            sys.executable,
            "tests/python/bench_worker.py",
            dataset_path,
            str(threads),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print("Error running worker:")
            print(result.stdout)
            print(result.stderr)
            sys.exit(1)

        t_tot, t_eng, p_mb, b_mb = parse_output(result.stdout, result.stderr)
        total_times.append(t_tot)
        engine_times.append(t_eng)
        peak_mbs.append(p_mb - b_mb)
        print(
            f"  Run {i + 1}: Total={t_tot:.4f}s, Engine={t_eng:.4f}s, Memory Delta={p_mb - b_mb:.1f} MB"
        )

    print("\nResults:")
    print(
        f"Total Time : Min={min(total_times):.4f}s, Median={statistics.median(total_times):.4f}s, Max={max(total_times):.4f}s, Mean={statistics.mean(total_times):.4f}s"
    )
    print(
        f"Engine Time: Min={min(engine_times):.4f}s, Median={statistics.median(engine_times):.4f}s, Max={max(engine_times):.4f}s, Mean={statistics.mean(engine_times):.4f}s"
    )
    print(
        f"Peak Mem(D): Min={min(peak_mbs):.1f}MB, Median={statistics.median(peak_mbs):.1f}MB, Max={max(peak_mbs):.1f}MB, Mean={statistics.mean(peak_mbs):.1f}MB"
    )


if __name__ == "__main__":
    datasets = {
        "100K": (100_000, "tests/data/bench_100k.csv"),
        "1M": (1_000_000, "tests/data/bench_1m.csv"),
        "2M": (2_000_000, "tests/data/bench_2m.csv"),
        "10M": (10_000_000, "tests/data/bench_10m.csv"),
    }

    for name, (rows, path) in datasets.items():
        generate_dataset(rows, path)

    for name, (rows, path) in datasets.items():
        iters = 5 if name == "10M" else 3
        run_benchmark(path, name, iterations=iters, threads=4)
