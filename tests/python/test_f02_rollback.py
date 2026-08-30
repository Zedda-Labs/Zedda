import pandas as pd
import zedda as zd
from zedda._models import CleaningPlan, CleanExecutionStatus
from zedda._clean_executor import execute_cleaning_transaction
from zedda._errors import ZeddaError
import pytest
import os
from unittest.mock import patch


def test_f02_clean_executor_false_rollback(tmp_path):
    df = pd.DataFrame({"A": [1, 2, 3]})
    target_file = tmp_path / "target.csv"
    df.to_csv(target_file, index=False)

    plan = CleaningPlan(proposed_changes=[], generated_from="test_plan")

    with patch(
        "os.replace", side_effect=PermissionError("Simulated locked file error")
    ):
        with pytest.raises(ZeddaError) as exc_info:
            execute_cleaning_transaction(
                df,
                plan,
                target_path=str(target_file),
                audit_actions=[],
                score_before=50,
                score_after=100,
            )

        err_msg = str(exc_info.value)
        # Should NOT just blindly say "rolled back" if it rolled back successfully,
        # but in this case, since write_versioned_backup succeeded and os.replace failed,
        # it SHOULD attempt rollback and succeed.
        assert "Successfully rolled back from backup" in err_msg
        assert "Simulated locked file error" in err_msg

    assert not (tmp_path / "target.csv.zedda-backup").exists()
    assert list(tmp_path.glob("target.csv.backup_*")) == []


def test_f02_clean_executor_fail_early(tmp_path):
    df = pd.DataFrame({"A": [1, 2, 3]})
    target_file = tmp_path / "target.csv"
    df.to_csv(target_file, index=False)

    plan = CleaningPlan(proposed_changes=[], generated_from="test_plan")

    # Fail during temp file write (before backup is created)
    with patch("pandas.DataFrame.to_csv", side_effect=OSError("Disk full")):
        with pytest.raises(ZeddaError) as exc_info:
            execute_cleaning_transaction(
                df,
                plan,
                target_path=str(target_file),
                audit_actions=[],
                score_before=50,
                score_after=100,
            )

        err_msg = str(exc_info.value)
        # Should not claim rollback since backup was never even created
        assert "Transaction failed before file modification" in err_msg
        assert "Disk full" in err_msg


def test_f02_new_target_rollback_removes_created_target(tmp_path):
    df = pd.DataFrame({"A": [1, 2, 3]})
    target_file = tmp_path / "new.csv"
    plan = CleaningPlan(proposed_changes=[], generated_from="test_plan")

    with (
        patch("json.dump", side_effect=OSError("manifest failed")),
        pytest.raises(ZeddaError, match="Removed the newly created target"),
    ):
        execute_cleaning_transaction(
            df,
            plan,
            target_path=str(target_file),
            audit_actions=[],
            score_before=50,
            score_after=100,
        )

    assert not target_file.exists()
