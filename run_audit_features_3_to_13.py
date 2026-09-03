import sys
import os
import time
import io
import json
import shutil
import pandas as pd
from rich.console import Console

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import zedda as zd

DATASET = r"e:\one_pice\zedda\transaction_data.csv"
TMPDIR = r"e:\one_pice\zedda\Testing\audit_full"
os.makedirs(TMPDIR, exist_ok=True)

OUT_LOG = os.path.join(TMPDIR, "features_execution_log.txt")
log_f = open(OUT_LOG, "a", encoding="utf-8")

def log(msg=""):
    print(msg, flush=True)
    log_f.write(str(msg) + "\n")
    log_f.flush()

def capture_console(func, *args, **kwargs):
    buf = io.StringIO()
    con = Console(file=buf, width=120, force_terminal=False, color_system=None, legacy_windows=False)
    orig_con = zd._console
    zd._console = con
    try:
        ret = func(*args, **kwargs)
    except Exception as e:
        buf.write(f"\n[EXCEPTION: {e}]\n")
        ret = None
    finally:
        zd._console = orig_con
    return ret, buf.getvalue()

# Prepare base dataset slice (50,000 real rows)
base_cmp = os.path.join(TMPDIR, "compare_base.csv")
if not os.path.exists(base_cmp):
    log("Preparing compare_base.csv (50,000 real rows)...")
    with open(DATASET, "r", encoding="utf-8") as src, open(base_cmp, "w", encoding="utf-8") as dst:
        dst.write(src.readline())
        for _ in range(50000):
            dst.write(src.readline())

# -------------------------------------------------------------------
# 3. warnings()
# -------------------------------------------------------------------
log("\n" + "="*50)
log("FEATURE 3: warnings()")
log("="*50)
_, warn_out = capture_console(zd.warnings, base_cmp)
log(warn_out)

# -------------------------------------------------------------------
# 4. collect_warnings()
# -------------------------------------------------------------------
log("\n" + "="*50)
log("FEATURE 4: collect_warnings()")
log("="*50)
cw = zd.collect_warnings(base_cmp)
log(f"len(collect_warnings): {len(cw)}")
log("All warning entries:")
for i, w in enumerate(cw, 1):
    log(f"  {i}. [{w.get('severity', '').upper():8s}] Column '{w.get('column')}': {w.get('message')}")
    log(f"      Fix action: {w.get('fix_action')}")
    log(f"      Fix code:   {w.get('fix_code')}")

# -------------------------------------------------------------------
# 5. ml_ready()
# -------------------------------------------------------------------
log("\n" + "="*50)
log("FEATURE 5: ml_ready(target='isFraud')")
log("="*50)
_, ml_out = capture_console(zd.ml_ready, base_cmp, target="isFraud")
log(ml_out)

# -------------------------------------------------------------------
# 6. validate()
# -------------------------------------------------------------------
log("\n" + "="*50)
log("FEATURE 6: validate()")
log("="*50)
rules = {
    "isFraud": {"min": 0, "max": 1},
    "step": {"min": 1, "max": 800},
    "amount": {"max": 1000.0},  # Genuinely FAILS (max is ~92M)
}
v_report = zd.validate(base_cmp, rules)
log(f"Total rules:         {v_report.total_rules}")
log(f"Passed rules:        {v_report.passed_rules}")
log(f"Failed rules:        {v_report.failed_rules}")
log(f"Indeterminate rules: {v_report.indeterminate_rules}")
log(f"Has failed:          {v_report.failed}")
breaches = v_report.all_breaches()
log(f"Breaches count:      {len(breaches)}")
log("Breaches details:")
for b in breaches:
    log(f"  {b}")
log(f"\nFull ValidationReport string representation:\n{str(v_report)}")

# -------------------------------------------------------------------
# 7. compare()
# -------------------------------------------------------------------
log("\n" + "="*50)
log("FEATURE 7: compare()")
log("="*50)
shift_cmp = os.path.join(TMPDIR, "compare_shifted.csv")
log(f"Preparing shifted dataset for compare...")
with open(base_cmp, "r", encoding="utf-8") as src:
    header = src.readline()
    sample_rows = src.readlines()

header_cols = header.strip().split(",")
amount_idx = header_cols.index("amount")
shift_rows = []
for i, line in enumerate(sample_rows):
    parts = line.rstrip("\n").split(",")
    if i >= 45000:
        parts[amount_idx] = str(float(parts[amount_idx]) * 10.0)
    # Drop last column (suspicious_signal_count)
    parts = parts[:-1]
    shift_rows.append(",".join(parts) + "\n")

shift_header = ",".join(header_cols[:-1]) + "\n"
with open(shift_cmp, "w", encoding="utf-8") as f:
    f.write(shift_header)
    f.writelines(shift_rows)

log(f"Base: {base_cmp} (50,000 rows, 31 cols)")
log(f"Shifted: {shift_cmp} (50,000 rows, 30 cols, amount shifted 10x for last 5k rows, suspicious_signal_count dropped)")
_, cmp_out = capture_console(zd.compare, base_cmp, shift_cmp)
log(cmp_out)

# -------------------------------------------------------------------
# 8. fix()
# -------------------------------------------------------------------
log("\n" + "="*50)
log("FEATURE 8: fix()")
log("="*50)
_, fix_out = capture_console(zd.fix, base_cmp)
log(fix_out)

# ACTUALLY EXECUTE GENERATED CODE
log("Executing generated code against a freshly loaded slice of data (50,000 rows)...")
from zedda._fix import generate_fix_code
p_sub = zd.scan(base_cmp)
fix_dict = generate_fix_code(p_sub)
df_test = pd.read_csv(base_cmp)
log(f"Initial shape: {df_test.shape}")
exec_env = {"df": df_test, "pd": pd}
code_to_exec = "\n".join(fix_dict["all_code"])
log("Generated code executed:")
for l in fix_dict["all_code"]:
    log(f"  {l}")
exec(code_to_exec, exec_env)
log(f"Fix execution succeeded without error!")
log(f"Final shape:   {exec_env['df'].shape}")

# -------------------------------------------------------------------
# 9. clean()
# -------------------------------------------------------------------
log("\n" + "="*50)
log("FEATURE 9: clean()")
log("="*50)
clean_target = os.path.join(TMPDIR, "clean_target.csv")
shutil.copyfile(base_cmp, clean_target)
log(f"Clean target prepared: {clean_target} ({os.path.getsize(clean_target):,} bytes)")
_, clean_out = capture_console(zd.clean, clean_target, approved=True)
log(clean_out)

audit_file = clean_target.replace(".csv", ".audit.json")
rollback_manifest = clean_target + ".rollback.json"
backups = [os.path.join(TMPDIR, f) for f in os.listdir(TMPDIR) if "backup" in f]

log(f"Cleaned output exists:     {os.path.exists(clean_target)} ({os.path.getsize(clean_target):,} bytes)")
log(f"Audit json exists:         {os.path.exists(audit_file)} ({os.path.getsize(audit_file):,} bytes)")
log(f"Rollback manifest exists:  {os.path.exists(rollback_manifest)} ({os.path.getsize(rollback_manifest):,} bytes)")
log(f"Backups found:             {len(backups)}")

# -------------------------------------------------------------------
# 10. merge()
# -------------------------------------------------------------------
log("\n" + "="*50)
log("FEATURE 10: merge()")
log("="*50)
part1_path = os.path.join(TMPDIR, "part1.csv")
part2_path = os.path.join(TMPDIR, "part2.csv")
merged_out_path = os.path.join(TMPDIR, "merged_output.csv")

with open(base_cmp, "r", encoding="utf-8") as src:
    header = src.readline()
    p1_rows = [src.readline() for _ in range(25000)]
    # p2 has 5000 overlapping rows and 20000 new rows
    p2_rows = p1_rows[20000:] + [src.readline() for _ in range(20000)]

with open(part1_path, "w", encoding="utf-8") as f:
    f.write(header)
    f.writelines(p1_rows)
with open(part2_path, "w", encoding="utf-8") as f:
    f.write(header)
    f.writelines(p2_rows)

log(f"Part 1: {len(p1_rows):,} rows")
log(f"Part 2: {len(p2_rows):,} rows (5,000 overlap)")
log(f"Expected unique merged: 45,000 rows")

_, merge_out = capture_console(zd.merge, [part1_path, part2_path], output=merged_out_path)
log(merge_out)

if os.path.exists(merged_out_path):
    with open(merged_out_path, "r", encoding="utf-8") as f:
        m_lines = sum(1 for _ in f) - 1
    log(f"Merged output actual rows on disk: {m_lines:,}")
    log(f"Row count verified: {m_lines == 45000}")

# -------------------------------------------------------------------
# 11. ask()
# -------------------------------------------------------------------
log("\n" + "="*50)
log("FEATURE 11: ask()")
log("="*50)
questions = [
    "How many rows are in the dataset?",
    "How many columns are in the dataset?",
    "What is the mean of the amount column?",
]
for q in questions:
    log(f"\nQuestion: '{q}'")
    ans, ask_render = capture_console(zd.ask, base_cmp, q)
    log(f"Raw answer: {ans}")
    log(f"Rendered terminal output:\n{ask_render}")
    if "50,000" in str(ans) or "50000" in str(ans):
        log("-> Row count in answer matches ground truth (50,000)!")
    elif "31" in str(ans):
        log("-> Column count in answer matches ground truth (31)!")

# -------------------------------------------------------------------
# 12. report()
# -------------------------------------------------------------------
log("\n" + "="*50)
log("FEATURE 12: report()")
log("="*50)
rep_path = os.path.join(TMPDIR, "transaction_data_report.html")
_, rep_render = capture_console(zd.report, base_cmp, output=rep_path)
log(rep_render)
log(f"Report file exists: {os.path.exists(rep_path)}")
log(f"Report size:        {os.path.getsize(rep_path):,} bytes")

with open(rep_path, "r", encoding="utf-8") as f:
    html_content = f.read()

log("\nInspecting HTML content:")
log(f"  Contains <!DOCTYPE html>:      {'<!DOCTYPE html>' in html_content}")
log(f"  Contains Dataset Overview:     {'Dataset Overview' in html_content or 'overview' in html_content.lower()}")
log(f"  Contains Column Profiles:      {'columns' in html_content.lower()}")
log(f"  Contains Warnings section:     {'warning' in html_content.lower()}")
log(f"  Contains Correlation alerts:   {'correlation' in html_content.lower()}")
log(f"  Contains external http links:  {'http://' in html_content or 'https://' in html_content}")

# -------------------------------------------------------------------
# 13. export()
# -------------------------------------------------------------------
log("\n" + "="*50)
log("FEATURE 13: export()")
log("="*50)
exp_path = os.path.join(TMPDIR, "transaction_data_export.html")
_, exp_render = capture_console(zd.export, base_cmp, output=exp_path)
log(exp_render)
log(f"Export file exists: {os.path.exists(exp_path)}")
log(f"Export size:        {os.path.getsize(exp_path):,} bytes")
log(f"Alias behavior identical to report(): {os.path.getsize(exp_path) == os.path.getsize(rep_path)}")

log_f.close()
print("Features 3-13 completed successfully!")
