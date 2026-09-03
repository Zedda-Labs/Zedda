import sys
import time
import os

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import zedda as zd

DATASET = r"e:\one_pice\zedda\transaction_data.csv"
print("===================================================================")
print("ITEM A.1: zd.ml_ready(DATASET, target='isFraud') on REAL 1.13 GB FILE")
print("===================================================================")
print(f"Target file: {DATASET}")
print(f"File size:   {os.path.getsize(DATASET):,} bytes")

t0 = time.perf_counter()
zd.ml_ready(DATASET, target="isFraud")
wall_duration = time.perf_counter() - t0

print(f"\n[EXECUTION COMPLETED]")
print(f"Wall-clock duration: {wall_duration:.2f} seconds ({wall_duration*1000:.1f} ms)")
