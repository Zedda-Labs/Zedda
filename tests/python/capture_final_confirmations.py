import zedda as zd
import pandas as pd
import uuid
import time
import os
import psutil
import threading
import json
from pprint import pprint


# Memory tracker from Phase 9
class MemoryTracker:
    def __init__(self):
        self.keep_running = True
        self.peak_mb = 0
        self.thread = None
        self.process = psutil.Process(os.getpid())

    def _track(self):
        while self.keep_running:
            try:
                mem_mb = self.process.memory_info().rss / (1024 * 1024)
                if mem_mb > self.peak_mb:
                    self.peak_mb = mem_mb
            except Exception:
                pass
            time.sleep(0.01)  # 10ms sampling

    def start(self):
        self.thread = threading.Thread(target=self._track)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.keep_running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        return self.peak_mb


def run_confirmations():
    print("=== CONFIRMATION 1: MEMORY CHECK FOR DISTINCT_VALUES_CAP=100,000 ===")

    csv_path = "tests/data/synthetic_500k_strings.csv"
    if not os.path.exists(csv_path):
        print("Generating 500,000 unique UUIDs...")
        data = {"uuid_col": [str(uuid.uuid4()) for _ in range(500000)]}
        pd.DataFrame(data).to_csv(csv_path, index=False)
        print(
            f"Generated {csv_path} ({os.path.getsize(csv_path) / (1024 * 1024):.1f} MB)"
        )
    else:
        print(f"Found {csv_path}")

    # Track baseline memory
    import gc

    gc.collect()
    process = psutil.Process(os.getpid())
    base_mb = process.memory_info().rss / (1024 * 1024)
    print(f"Baseline Memory: {base_mb:.1f} MB")

    tracker = MemoryTracker()
    tracker.start()

    t0 = time.time()
    print("Starting zedda.scan()...")
    p = zd.scan(csv_path)
    t1 = time.time()

    peak_mb = tracker.stop()
    print(f"Scan completed in {t1 - t0:.2f} seconds.")
    print(
        f"Peak Memory during scan: {peak_mb:.1f} MB (Delta: {peak_mb - base_mb:.1f} MB)"
    )

    col = next(c for c in p.columns if c.name == "uuid_col")
    print("\nColumn Profile for 'uuid_col':")
    print(f"  non_null_count: {col.non_null_count}")
    print(f"  unique_approx: {col.unique_approx}")
    print(f"  unique_exact: {col.unique_exact}")
    print(f"  exact_unique_valid: {col.exact_unique_valid}")
    # We expect exact_unique_valid = False since 500,000 > 100,000 cap!
    print(
        "  Success: The C++ cap worked successfully!"
        if not col.exact_unique_valid
        else "  FAIL: Cap was not applied!"
    )

    print("\n=== CONFIRMATION 2: validate() RE-TEST ===")
    rules = {
        "Age": {"min": 0, "max": 100, "max_null_pct": 25.0},
        "Survived": {"allowed_values": [0, 1]},
        "PassengerId": {"is_unique": True, "max_null_pct": 0.0},
    }
    report = zd.validate("tests/data/titanic.csv", rules=rules)

    print("\nValidation Report:")
    # We just print the report directly; we might need to handle encoding if run directly on windows terminal,
    # but run_command handles it via UTF-8 if properly captured.
    print(report)

    print("\nBreaches Check:")
    for b in report.all_breaches():
        print(f"  Breach: {b.column} - {b.rule} - {b.severity} ({b.reason})")

    survived_breaches = [b for b in report.all_breaches() if b.column == "Survived"]
    if not survived_breaches:
        print("\nSUCCESS: Survived allowed_values rule PASSED!")
    else:
        print("\nFAIL: Survived rule breached or was indeterminate!")

    print("\n=== CONFIRMATION 3: collect_warnings() DUPLICATE RE-CHECK ===")
    from zedda._warnings import collect_warnings

    titanic_profile = zd.scan("tests/data/titanic.csv")
    warnings_list = collect_warnings(titanic_profile)

    print("Full Warnings List:")
    for w in warnings_list:
        print(
            f"- Column: {w['column']}, Type: {w['category']}, Severity: {w['severity']}, Action: {w['action_type']}"
        )

    # Check duplicates explicitly
    seen = set()
    has_duplicates = False
    for w in warnings_list:
        sig = (w["column"], w["category"])
        if sig in seen:
            has_duplicates = True
            print(f"  [ERROR] DUPLICATE FOUND: {sig}")
        seen.add(sig)

    if not has_duplicates:
        print("\nSUCCESS: No exact-duplicate entries found in collect_warnings()!")


if __name__ == "__main__":
    run_confirmations()
