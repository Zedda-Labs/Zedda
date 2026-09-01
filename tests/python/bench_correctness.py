import os
import sys
import subprocess
import time


def parse_output(stdout, stderr):
    total_time = 0.0
    for line in stdout.splitlines():
        if line.startswith("__BENCH_TOTAL_TIME__:"):
            total_time = float(line.split(":")[1])
    return total_time


def run_bench(name):
    cmd = [
        sys.executable,
        "tests/python/bench_worker.py",
        "tests/data/bench_1m.csv",
        "4",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("Error in worker", file=sys.stderr)
        sys.exit(1)
    return parse_output(result.stdout, result.stderr)


def patch_file(path, old, new):
    with open(path, encoding="utf-8") as f:
        content = f.read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.replace(old, new))


def compile():
    cmd = [sys.executable, "-m", "pip", "install", "-e", "."]
    subprocess.run(cmd, capture_output=True, text=True)


def log(msg, file):
    print(msg)
    file.write(msg + "\n")
    file.flush()
    sys.stdout.flush()


if __name__ == "__main__":
    col_acc = "include/zedda/column_accumulator.hpp"
    prof_bld = "src/core/profile_builder.cpp"

    with open("bench_results.txt", "w", encoding="utf-8") as out_f:
        # 1. Baseline
        log("Building baseline...", out_f)
        compile()
        base_t = run_bench("baseline")
        log(f"Baseline: {base_t:.2f}s", out_f)

        # 2. No Pre-pass
        log("Testing no pre-pass...", out_f)
        patch_file(prof_bld, "PRE_PASS_ROWS_CAP = 5000;", "PRE_PASS_ROWS_CAP = 0;")
        compile()
        nopre_t = run_bench("nopre")
        log(f"No Pre-pass: {nopre_t:.2f}s (Overhead: {base_t - nopre_t:.2f}s)", out_f)
        patch_file(
            prof_bld, "PRE_PASS_ROWS_CAP = 0;", "PRE_PASS_ROWS_CAP = 5000;"
        )  # Revert

        # 3. No Exact Numeric
        log("Testing no exact numeric...", out_f)
        patch_file(col_acc, "EXACT_NUMERIC_CAP = 100'000;", "EXACT_NUMERIC_CAP = 0;")
        compile()
        nonum_t = run_bench("nonum")
        log(
            f"No Exact Numeric: {nonum_t:.2f}s (Overhead: {base_t - nonum_t:.2f}s)",
            out_f,
        )
        patch_file(
            col_acc, "EXACT_NUMERIC_CAP = 0;", "EXACT_NUMERIC_CAP = 100'000;"
        )  # Revert

        # 4. No Exact String
        log("Testing no exact string...", out_f)
        patch_file(
            col_acc, "DISTINCT_VALUES_CAP = 100'000;", "DISTINCT_VALUES_CAP = 0;"
        )
        compile()
        nostr_t = run_bench("nostr")
        log(
            f"No Exact String: {nostr_t:.2f}s (Overhead: {base_t - nostr_t:.2f}s)",
            out_f,
        )
        patch_file(
            col_acc, "DISTINCT_VALUES_CAP = 0;", "DISTINCT_VALUES_CAP = 100'000;"
        )  # Revert

        log("\n--- Summary (1M rows) ---", out_f)
        log(f"Base: {base_t:.2f}s", out_f)
        log(f"Pre-pass cost: {base_t - nopre_t:.2f}s", out_f)
        log(f"Numeric Exact cost: {base_t - nonum_t:.2f}s", out_f)
        log(f"String Exact cost: {base_t - nostr_t:.2f}s", out_f)
