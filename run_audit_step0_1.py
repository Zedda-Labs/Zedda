import sys
import os
import time
import io
import json
import shutil
import threading
import psutil
import pandas as pd
from rich.console import Console

# Force UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import zedda as zd
from zedda._profile_print import _print_report

DATASET = r"e:\one_pice\zedda\transaction_data.csv"
TMPDIR = r"e:\one_pice\zedda\Testing\audit_full"
os.makedirs(TMPDIR, exist_ok=True)

OUT_LOG = os.path.join(TMPDIR, "audit_execution_log.txt")
log_f = open(OUT_LOG, "w", encoding="utf-8")

def log(msg=""):
    print(msg, flush=True)
    log_f.write(str(msg) + "\n")
    log_f.flush()

log("===================================================================")
log("ZEDDA v0.5 FULL-SCALE PRODUCTION STRESS & VERIFICATION AUDIT")
log("===================================================================")

# -------------------------------------------------------------------
# STEP 0: Environment Integrity Proof
# -------------------------------------------------------------------
log("\n--- STEP 0: ENVIRONMENT INTEGRITY PROOF ---")
import hashlib
pyd_path = zd.fasteda_core.__file__
imported_sha = hashlib.sha256(open(pyd_path, 'rb').read()).hexdigest()
build_pyd = r"e:\one_pice\zedda\build_py312\Release\fasteda_core.cp312-win_amd64.pyd"
build_sha = hashlib.sha256(open(build_pyd, 'rb').read()).hexdigest()

log(f"zedda.__file__:           {zd.__file__}")
log(f"fasteda_core.__file__:    {pyd_path}")
log(f"Imported SHA256:          {imported_sha}")
log(f"Build SHA256:             {build_sha}")
log(f"SHA256 Match:             {imported_sha == build_sha}")

# Check stray python processes
curr_pid = os.getpid()
stray = [p.info for p in psutil.process_iter(['pid', 'name']) if 'python' in (p.info['name'] or '').lower() and p.info['pid'] != curr_pid]
log(f"Stray Python processes:   {len(stray)}")

# -------------------------------------------------------------------
# DATASET GROUND TRUTH
# -------------------------------------------------------------------
log("\n--- DATASET GROUND TRUTH ---")
fsize = os.path.getsize(DATASET)
log(f"Path:                     {DATASET}")
log(f"File size in bytes:       {fsize:,} bytes ({fsize / (1024**3):.3f} GiB)")

with open(DATASET, 'rb') as f:
    header_line = f.readline().decode('utf-8', errors='ignore').strip()
    cols = header_line.split(',')
    row_count = sum(chunk.count(b'\n') for chunk in iter(lambda: f.read(1024*1024*8), b''))

log(f"Row count (excl header):  {row_count:,}")
log(f"Column count:             {len(cols)}")
log(f"Columns:                  {cols}")

# -------------------------------------------------------------------
# STEP 1: Sampling Behavior Check
# -------------------------------------------------------------------
log("\n--- STEP 1: SAMPLING BEHAVIOR CHECK ---")
log("Checking default zd.scan(DATASET):")
t0 = time.perf_counter()
p_full = zd.scan(DATASET)
t_full = (time.perf_counter() - t0) * 1000
log(f"  p_full.is_sampled:      {p_full.is_sampled}")
log(f"  p_full.num_rows:        {p_full.num_rows:,} (vs total {row_count:,})")
log(f"  p_full.scan_time_ms:    {p_full.scan_time_ms}")
log(f"  Wall-clock time:        {t_full:.1f} ms")

log("\nChecking explicit zd.scan(DATASET, sample_size=2_000_000):")
t0 = time.perf_counter()
p_sampled = zd.scan(DATASET, sample_size=2_000_000)
t_sampled = (time.perf_counter() - t0) * 1000
log(f"  p_sampled.is_sampled:   {p_sampled.is_sampled}")
log(f"  p_sampled.num_rows:     {p_sampled.num_rows:,} (vs total {row_count:,})")
log(f"  p_sampled.scan_time_ms: {p_sampled.scan_time_ms}")
log(f"  Wall-clock time:        {t_sampled:.1f} ms")

import pickle
with open(os.path.join(TMPDIR, "p_full.pkl"), "wb") as pf:
    pickle.dump(p_full, pf)
with open(os.path.join(TMPDIR, "p_sampled.pkl"), "wb") as pf:
    pickle.dump(p_sampled, pf)
log(f"Cached p_full.pkl and p_sampled.pkl to {TMPDIR}")

# Render profile for both
def capture_render(profile_obj):
    buf = io.StringIO()
    con = Console(file=buf, width=120, force_terminal=False, color_system=None, legacy_windows=False)
    orig_con = zd._console
    zd._console = con
    try:
        _print_report(profile_obj)
    except Exception as e:
        buf.write(f"\n[EXCEPTION DURING RENDER: {e}]\n")
    finally:
        zd._console = orig_con
    return buf.getvalue()

log("\nRendered profile for p_full (first 1000 chars):")
log(capture_render(p_full)[:1000])

log("\nRendered profile for p_sampled:")
samp_render = capture_render(p_sampled)
log(samp_render[:1000])
if "⚡ SAMPLED" in samp_render or "[SAMPLED]" in samp_render:
    log("⚡ SAMPLED indicator found in terminal output!")
else:
    log("Note: SAMPLED indicator check in rendered output.")

log_f.close()
print("Phase 1 complete, saved to log.")
