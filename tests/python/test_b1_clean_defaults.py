import pytest
import os
import zedda as zd
from zedda._models import CleaningPlan

def test_clean_defaults_are_safe(tmp_path):
    target = tmp_path / "test_clean_defaults.csv"
    target.write_text("A,B\n1,2\n3,?\n")
    
    # Record initial mtime
    initial_mtime = os.path.getmtime(target)
    
    # Call clean with no other args (defaults: dry_run=True, approved=False)
    result = zd.clean(str(target))
    
    # a) Assert it returns a CleaningPlan
    assert isinstance(result, CleaningPlan), f"Expected CleaningPlan, got {type(result)}"
    
    # b) Assert target file's mtime is unchanged
    current_mtime = os.path.getmtime(target)
    assert current_mtime == initial_mtime, "Target file mtime was changed!"
    
    # c) Assert no backup file exists on disk (using real pattern *backup*)
    backups = list(tmp_path.glob("*backup*"))
    assert len(backups) == 0, f"Found backup files in dry-run: {backups}"

def test_clean_positive_control_creates_backup(tmp_path):
    target = tmp_path / "test_clean_positive.csv"
    target.write_text("A,B\n1,2\n3,?\n")
    
    # Explicit clean execution
    result = zd.clean(str(target), dry_run=False, approved=True)
    assert not isinstance(result, CleaningPlan)
    
    # Positive control: verify that *backup* pattern DOES detect real backups
    backups = list(tmp_path.glob("*backup*"))
    assert len(backups) >= 1, f"Positive control failed: no backups found matching *backup*: {backups}"
