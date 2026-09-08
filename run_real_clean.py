import sys
import time
import os
import glob

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import zedda as zd

DATASET = r"e:\one_pice\zedda\transaction_data.csv"
TMPDIR = r"e:\one_pice\zedda\Testing\audit_full"
CLEAN_OUT = os.path.join(TMPDIR, "transaction_data_cleaned.csv")
os.makedirs(TMPDIR, exist_ok=True)

# Clean up prior test output if exists
for f in glob.glob(os.path.join(TMPDIR, "*cleaned*")):
    try:
        os.remove(f)
    except Exception:
        pass

print("===================================================================")
print("ITEM A.2: zd.clean(DATASET, output=...) on REAL 1.13 GB FILE")
print("===================================================================")
print(f"Source file:      {DATASET} ({os.path.getsize(DATASET):,} bytes)")
print(f"Target output:    {CLEAN_OUT}")

t0 = time.perf_counter()
res = zd.clean(DATASET, output=CLEAN_OUT, approved=True)
wall_duration = time.perf_counter() - t0

print(f"\n[CLEAN EXECUTION COMPLETED]")
print(f"Wall-clock duration: {wall_duration:.2f} seconds ({wall_duration*1000:.1f} ms)")

# Check on disk
audit_file = CLEAN_OUT.replace(".csv", ".audit.json")
rollback_file = CLEAN_OUT + ".rollback.json"
backups = glob.glob(os.path.join(TMPDIR, "*backup*")) + glob.glob(DATASET + "*backup*")

print("\n--- ON-DISK VERIFICATION ---")
print(f"Cleaned output file exists:    {os.path.exists(CLEAN_OUT)}")
if os.path.exists(CLEAN_OUT):
    print(f"Cleaned output file size:      {os.path.getsize(CLEAN_OUT):,} bytes")

print(f"Audit trail JSON exists:       {os.path.exists(audit_file)}")
if os.path.exists(audit_file):
    print(f"Audit trail JSON size:         {os.path.getsize(audit_file):,} bytes")

print(f"Rollback manifest exists:      {os.path.exists(rollback_file)}")
if os.path.exists(rollback_file):
    print(f"Rollback manifest size:        {os.path.getsize(rollback_file):,} bytes")

print(f"Backup files found:            {len(backups)}")
for b in backups:
    print(f"  Backup: {b} ({os.path.getsize(b):,} bytes)")
