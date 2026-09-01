"""
zedda._clean_executor — transactional execution engine for dataset cleaning.

Phase 7.2: Implements the Plan -> Approval -> Transactional Execute model (Section 4.4).
Steps:
1. write_temp_output
2. post_write_validate
3. fsync
4. write_versioned_backup
5. atomic_replace
6. write_rollback_manifest

Rollback guarantees: If any step fails before atomic replace, temp artifacts
are cleaned up and the original file is left untouched.
"""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import time
from typing import Any

from ._errors import ZeddaError
from ._models import (
    CleanExecution,
    CleanExecutionStatus,
    CleaningPlan,
)


@contextmanager
def _target_lock(target: Path):
    """Serialize transactions for one target across threads and processes."""
    lock_name = hashlib.sha256(str(target).encode("utf-8")).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / f"zedda-clean-{lock_name}.lock"
    with open(lock_path, "a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ZeddaError(
                    f"Another cleaning transaction is active for '{target}'"
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ZeddaError(
                    f"Another cleaning transaction is active for '{target}'"
                ) from exc
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _with_target_lock(function):
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any):
        target_path = kwargs.get("target_path")
        if target_path is None and len(args) >= 3:
            target_path = args[2]
        if target_path is None:
            return function(*args, **kwargs)
        with _target_lock(Path(target_path).resolve()):
            return function(*args, **kwargs)

    return wrapped


@_with_target_lock
def execute_cleaning_transaction(
    df: Any,
    plan: CleaningPlan,
    target_path: str | Path | None,
    audit_actions: list[dict[str, Any]],
    score_before: int,
    score_after: int,
    version: str = "0.4.8",
    approved_by: str = "user",
) -> tuple[CleanExecution, str | None, str | None, str | None]:
    """Execute a dataset cleaning plan transactionally.

    Returns:
        tuple of (execution_record, final_output_path, backup_path, manifest_path)
    """
    if target_path is None:
        # In-memory DataFrame operation with no file target
        exec_record = CleanExecution(
            plan_id=plan.generated_from,
            approved_by=approved_by,
            status=CleanExecutionStatus.COMPLETE,
        )
        return exec_record, None, None, None

    target = Path(target_path).resolve()
    target_parent = target.parent
    if not target_parent.exists():
        raise ZeddaError(f"Target directory does not exist: '{target_parent}'")

    ext = target.suffix.lower()
    timestamp = int(time.time())
    transaction_id = uuid.uuid4().hex
    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".tmp_clean_{transaction_id}_",
        suffix=target.suffix,
        dir=target_parent,
    )
    os.close(temp_fd)
    temp_file = Path(temp_name)
    versioned_backup = target_parent / f"{target.name}.backup_{transaction_id}"
    legacy_backup = target_parent / f"{target.name}.zedda-backup"
    manifest_file = target_parent / f"{target.name}.rollback.json"
    target_existed_before = target.exists()
    manifest_existed_before = manifest_file.exists()
    previous_manifest = manifest_file.read_bytes() if manifest_existed_before else None
    legacy_backup_existed_before = legacy_backup.exists()

    steps_taken: list[str] = []
    backup_created: str | None = None

    try:
        # Step 1: write_temp_output
        if ext in (".parquet", ".arrow"):
            df.to_parquet(str(temp_file), index=False)
        else:
            df.to_csv(str(temp_file), index=False)
        steps_taken.append("write_temp_output")

        # Step 2: post_write_validate
        if not temp_file.exists() or temp_file.stat().st_size == 0:
            raise ZeddaError(
                "Cleaned temp file validation failed: file is empty or missing"
            )
        steps_taken.append("post_write_validate")

        # Step 3: fsync
        try:
            with open(temp_file, "r+b") as f:
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            pass
        steps_taken.append("fsync")

        # Step 4: write_versioned_backup (if target file exists)
        if target_existed_before:
            import shutil

            # Versioned timestamp backup
            shutil.copy2(str(target), str(versioned_backup))
            # Legacy pointer backup (if not already present)
            if not legacy_backup.exists():
                shutil.copy2(str(target), str(legacy_backup))
            backup_created = str(versioned_backup)
            steps_taken.append("write_versioned_backup")

        # Step 5: atomic_replace
        os.replace(str(temp_file), str(target))
        steps_taken.append("atomic_replace")

        # Step 6: write_rollback_manifest
        manifest_data = {
            "plan_id": plan.generated_from,
            "target_file": target.name,
            "timestamp": timestamp,
            "transaction_id": transaction_id,
            "zedda_version": version,
            "score_before": score_before,
            "score_after": score_after,
            "backup_file": Path(backup_created).name if backup_created else None,
            "legacy_backup": legacy_backup.name if legacy_backup.exists() else None,
            "actions": audit_actions,
            "status": "COMPLETE",
        }
        with open(manifest_file, "w", encoding="utf-8") as mf:
            json.dump(manifest_data, mf, indent=2, ensure_ascii=False)
        steps_taken.append("write_rollback_manifest")

        exec_record = CleanExecution(
            plan_id=plan.generated_from,
            approved_by=approved_by,
            steps=steps_taken,
            status=CleanExecutionStatus.COMPLETE,
        )
        return exec_record, str(target), backup_created, str(manifest_file)

    except Exception as e:
        # Transaction rollback on failure
        rollback_errors: list[str] = []
        manifest_restored = True
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception as cleanup_err:
                rollback_errors.append(f"temporary-file cleanup failed: {cleanup_err}")

        # Restore or remove the manifest if a failure occurred after it was
        # opened. A partially written manifest is not a valid recovery record.
        try:
            if manifest_existed_before and previous_manifest is not None:
                manifest_file.write_bytes(previous_manifest)
            elif not manifest_existed_before and manifest_file.exists():
                manifest_file.unlink()
        except Exception as manifest_err:
            manifest_restored = False
            rollback_errors.append(
                f"rollback manifest restoration failed: {manifest_err}"
            )

        status = CleanExecutionStatus.FAILED
        rollback_msg = "Transaction failed before file modification."

        if (
            "write_versioned_backup" in steps_taken
            and backup_created
            and Path(backup_created).exists()
        ):
            import shutil

            try:
                shutil.copy2(backup_created, str(target))
                status = CleanExecutionStatus.ROLLED_BACK
                rollback_msg = (
                    "Transaction failed. Successfully rolled back from backup."
                )
            except Exception as rollback_err:
                status = CleanExecutionStatus.FAILED
                rollback_msg = (
                    f"CRITICAL: Transaction failed AND rollback failed: {rollback_err}"
                )
        elif (
            "atomic_replace" in steps_taken
            and not target_existed_before
            and target.exists()
        ):
            try:
                target.unlink()
                status = CleanExecutionStatus.ROLLED_BACK
                rollback_msg = "Transaction failed. Removed the newly created target during rollback."
            except Exception as rollback_err:
                status = CleanExecutionStatus.FAILED
                rollback_msg = (
                    "CRITICAL: Transaction failed AND new-target rollback failed: "
                    f"{rollback_err}"
                )

        # Remove artifacts created by this transaction only after the target
        # itself is known to be restored. Preserve them when recovery failed.
        target_restored = manifest_restored and (
            status == CleanExecutionStatus.ROLLED_BACK
            or "atomic_replace" not in steps_taken
        )
        if target_restored:
            for artifact in (versioned_backup,):
                if artifact.exists():
                    try:
                        artifact.unlink()
                    except Exception as cleanup_err:
                        rollback_errors.append(
                            f"backup cleanup failed for '{artifact}': {cleanup_err}"
                        )
            if not legacy_backup_existed_before and legacy_backup.exists():
                try:
                    legacy_backup.unlink()
                except Exception as cleanup_err:
                    rollback_errors.append(
                        f"backup cleanup failed for '{legacy_backup}': {cleanup_err}"
                    )

        if rollback_errors:
            status = CleanExecutionStatus.FAILED
            rollback_msg = (
                f"{rollback_msg} Rollback errors: {'; '.join(rollback_errors)}"
            )

        exec_record = CleanExecution(
            plan_id=plan.generated_from,
            approved_by=approved_by,
            steps=steps_taken,
            status=status,
        )
        raise ZeddaError(f"{rollback_msg} Original error: {e}") from e
