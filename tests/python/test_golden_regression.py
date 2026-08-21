import os
import json
import pytest
import zedda as zd
import glob
import shutil

base_dir = "tests/fixtures/regression"
golden_dir = "tests/fixtures/golden"

fixtures = sorted(glob.glob(os.path.join(base_dir, "*.*")))

def remove_non_deterministic(obj):
    if isinstance(obj, dict):
        obj.pop("time_ms", None)
        obj.pop("scan_time", None)
        obj.pop("scan_time_ms", None)
        for k, v in obj.items():
            remove_non_deterministic(v)
    elif isinstance(obj, list):
        for item in obj:
            remove_non_deterministic(item)
    return obj

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

@pytest.mark.parametrize("fixture", fixtures, ids=[os.path.basename(f) for f in fixtures])
def test_golden_regression(fixture):
    name = os.path.basename(fixture)
    golden_file = os.path.join(golden_dir, f"{name}.golden.json")
    
    with open(golden_file, "r") as f:
        golden = json.load(f)
        
    scan_res = safe_run(zd.scan, fixture)
    profile_res = safe_run(zd.profile, fixture)
    warnings_res = safe_run(zd.warnings, fixture)
    ml_ready_res = safe_run(zd.ml_ready, fixture)
    validate_res = safe_run(zd.validate, fixture, {})
    
    temp_fixture = fixture + ".temp"
    shutil.copy2(fixture, temp_fixture)
    compare_res = safe_run(zd.compare, fixture, temp_fixture)
    
    temp_output = temp_fixture + ".out"
    clean_res = safe_run(zd.clean, temp_fixture, output=temp_output)
    
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
    
    # Remove timing and other non-deterministic keys
    remove_non_deterministic(output)
    remove_non_deterministic(golden)
    
    output_str = json.dumps(output, indent=2, default=str)
    golden_str = json.dumps(golden, indent=2, default=str)
    
    assert output_str == golden_str, f"Regression detected for {name}"
