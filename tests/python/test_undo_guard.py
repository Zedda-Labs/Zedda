import zedda as zd
import pytest
from zedda._errors import ZeddaError


def test_m6_undo_guard_prevents_overwrite_of_edits(tmp_path):
    p = tmp_path / "m6_test.csv"
    p.write_text("a,b\n1,2\n3,4\n")

    # run clean to create backup
    zd.clean(str(p), dry_run=False, approved=True)

    # append a line to simulate a user edit after cleaning
    p.write_text(p.read_text() + "5,6\n")

    # undo without force should raise ZeddaError
    with pytest.raises(ZeddaError, match="has been modified since it was cleaned"):
        zd.clean.undo(str(p))


def test_m6_undo_force_overwrites_edits(tmp_path):
    p = tmp_path / "m6_test2.csv"
    p.write_text("a,b\n1,2\n3,4\n")

    # run clean to create backup
    zd.clean(str(p), dry_run=False, approved=True)

    # append a line
    p.write_text(p.read_text() + "5,6\n")

    # undo with force should succeed
    zd.clean.undo(str(p), force=True)
    assert p.read_text() == "a,b\n1,2\n3,4\n"


def test_m6_double_undo_fails(tmp_path):
    p = tmp_path / "m6_test3.csv"
    p.write_text("a,b\n1,2\n")
    zd.clean(str(p), dry_run=False, approved=True)
    zd.clean.undo(str(p))
    with pytest.raises(ZeddaError, match="No backup found"):
        zd.clean.undo(str(p))


def test_m6_legacy_backup_restoration(tmp_path):
    p = tmp_path / "m6_legacy.csv"
    orig = "a,b\nlegacy,1\n"
    p.write_text("a,b\nchanged,2\n")

    # Create legacy backup directly
    legacy_backup = p.parent / f"{p.name}.zedda-backup"
    legacy_backup.write_text(orig)

    # Undo without force should fail
    with pytest.raises(
        ZeddaError,
        match="Cannot verify integrity: backup .* lacks a cryptographic hash",
    ):
        zd.clean.undo(str(p))

    # Undo with force should restore legacy
    zd.clean.undo(str(p), force=True)
    assert p.read_text() == orig
    # Double undo should fail
    with pytest.raises(ZeddaError, match="No backup found"):
        zd.clean.undo(str(p))


def test_m6_pre_hash_manifest_restoration(tmp_path):
    import json

    p = tmp_path / "m6_prehash.csv"
    orig = "a,b\nprehash,1\n"
    p.write_text("a,b\nchanged,2\n")

    # Create backup
    backup_file = p.parent / f"{p.name}.backup_abc123"
    backup_file.write_text(orig)

    # Create manifest without post_clean_hash
    manifest = p.parent / f"{p.name}.rollback.json"
    manifest.write_text(json.dumps({"backup_file": backup_file.name}))

    # Should fail without force since no hash check can be done
    with pytest.raises(
        ZeddaError,
        match="Cannot verify integrity: backup .* lacks a cryptographic hash",
    ):
        zd.clean.undo(str(p))

    # Should restore fine with force
    zd.clean.undo(str(p), force=True)
    assert p.read_text() == orig


def test_undo_clean_refuses_edited_file(tmp_path):
    from zedda._clean import undo_clean

    p = tmp_path / "undo_clean_guard.csv"
    p.write_text("a,b\n1,2\n")

    zd.clean(str(p), dry_run=False, approved=True)

    # User modifies file post-clean
    p.write_text("a,b\n1,2\n3,4\n")

    # undo_clean defaults to force=False and refuses
    with pytest.raises(ZeddaError, match="has been modified since it was cleaned"):
        undo_clean(str(p))

    # force=True succeeds
    undo_clean(str(p), force=True)
    assert p.read_text() == "a,b\n1,2\n"

