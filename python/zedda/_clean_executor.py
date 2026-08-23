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
import os
from pathlib import Path
import time
from typing import Any

from ._errors import ZeddaError
from ._models import (
    CleanExecution,
    CleanExecutionStatus,
    CleaningPlan,
)


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
    temp_file = target_parent / f".tmp_clean_{timestamp}_{target.name}"
    versioned_backup = target_parent / f"{target.name}.backup_{timestamp}"
    legacy_backup = target_parent / f"{target.name}.zedda-backup"
    manifest_file = target_parent / f"{target.name}.rollback.json"

    steps_taken: list[str] = []

    try:
        # Step 1: write_temp_output
        if ext in (".parquet", ".arrow"):
            df.to_parquet(str(temp_file), index=False)
        else:
            df.to_csv(str(temp_file), index=False)
        steps_taken.append("write_temp_output")

        # Step 2: post_write_validate
        if not temp_file.exists() or temp_file.stat().st_size == 0:
            raise ZeddaError("Cleaned temp file validation failed: file is empty or missing")
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
        backup_created: str | None = None
        if target.exists():
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
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass

        exec_record = CleanExecution(
            plan_id=plan.generated_from,
            approved_by=approved_by,
            steps=steps_taken,
            status=CleanExecutionStatus.ROLLED_BACK,
        )
        raise ZeddaError(f"Cleaning transaction failed and rolled back: {e}") from e
