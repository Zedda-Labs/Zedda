import hashlib
import os
import pytest
from pathlib import Path
import zedda as zd
from zedda._clean import undo_clean


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_clean_undo_rollback_fidelity(tmp_path):
    target = tmp_path / "rollback_test.csv"
    original_content = "id,value,category\n1,100,A\n2,?,A\n3,300,B\n"
    target.write_text(original_content, encoding="utf-8")

    orig_sha256 = sha256_file(target)

    # Run clean with explicit execution
    res = zd.clean(str(target), dry_run=False, approved=True)

    # Assert file changed
    assert target.exists()
    cleaned_sha256 = sha256_file(target)
    assert cleaned_sha256 != orig_sha256, "Expected file content to change after clean"

    # Restore via zd.clean.undo
    zd.clean.undo(str(target))

    # Assert restored sha256 exactly equals original
    restored_sha256 = sha256_file(target)
    assert restored_sha256 == orig_sha256, (
        f"Rollback mismatch: {restored_sha256} != {orig_sha256}"
    )


def test_clean_undo_restores_from_manifest_when_legacy_backup_deleted(tmp_path):
    target = tmp_path / "manifest_rollback_test.csv"
    original_content = "col_a,col_b\n1,10\n2,20\n3,?\n"
    target.write_text(original_content, encoding="utf-8")

    orig_sha256 = sha256_file(target)

    # Execute clean
    zd.clean(str(target), dry_run=False, approved=True)
    assert sha256_file(target) != orig_sha256

    # Delete legacy backup if present
    legacy = tmp_path / f"{target.name}.zedda-backup"
    if legacy.exists():
        legacy.unlink()

    # Ensure manifest and versioned backup exist
    manifest = tmp_path / f"{target.name}.rollback.json"
    assert manifest.exists()

    # Restore using zd.clean.undo (should resolve via manifest)
    zd.clean.undo(str(target))
    assert sha256_file(target) == orig_sha256


def test_undo_clean_helper_delegates(tmp_path):
    target = tmp_path / "helper_rollback_test.csv"
    original_content = "x,y\n10,20\n30,?\n"
    target.write_text(original_content, encoding="utf-8")

    orig_sha256 = sha256_file(target)
    zd.clean(str(target), dry_run=False, approved=True)
    assert sha256_file(target) != orig_sha256

    # Restore using legacy undo_clean helper
    undo_clean(str(target))
    assert sha256_file(target) == orig_sha256
