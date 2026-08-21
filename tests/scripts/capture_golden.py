import os
import json
import zedda as zd
import glob
import shutil

base_dir = "tests/fixtures/regression"
golden_dir = "tests/fixtures/golden"
os.makedirs(golden_dir, exist_ok=True)

fixtures = sorted(glob.glob(os.path.join(base_dir, "*.*")))

def safe_run(func, *args, **kwargs):
    try:
        res = func(*args, **kwargs)
        if hasattr(res, 'to_dict'):
            return res.to_dict()
        elif isinstance(res, dict):
            return res
        return str(res)
    except Exception as e:
        return {"error": type(e).__name__, "message": str(e)}

for fixture in fixtures:
    name = os.path.basename(fixture)
    print(f"Capturing {name}...")
    
    scan_res = safe_run(zd.scan, fixture)
    profile_res = safe_run(zd.profile, fixture)
    warnings_res = safe_run(zd.warnings, fixture)
    ml_ready_res = safe_run(zd.ml_ready, fixture)
    validate_res = safe_run(zd.validate, fixture, {})
    
    # For clean and compare, use a temp copy to avoid destruction
    temp_fixture = fixture + ".temp"
    shutil.copy2(fixture, temp_fixture)
    
    compare_res = safe_run(zd.compare, fixture, temp_fixture)
    
    # Try clean
    temp_output = temp_fixture + ".out"
    clean_res = safe_run(zd.clean, temp_fixture, output=temp_output)
    
    # cleanup temp files
    for f in [temp_fixture, temp_output, temp_fixture + ".zedda-backup", temp_fixture.split('.')[0] + ".audit.json"]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except:
                pass
                
    output = {
        "scan": scan_res,
        "profile": profile_res,
        "warnings": warnings_res,
        "ml_ready": ml_ready_res,
        "validate": validate_res,
        "compare": compare_res,
        "clean": clean_res
    }
    
    with open(os.path.join(golden_dir, f"{name}.golden.json"), "w") as f:
        json.dump(output, f, indent=2, default=str)
