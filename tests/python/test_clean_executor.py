import json
import pytest
import pandas as pd
import zedda as zd
from zedda._clean import clean, undo_clean
from zedda._clean_executor import _target_lock, execute_cleaning_transaction
from zedda._errors import ZeddaError
from zedda._models import CleaningPlan, CleanExecutionStatus, DatasetProfile
from unittest.mock import patch


def test_clean_transactional_execution(tmp_path):
    df = pd.DataFrame(
        {
            "id": range(100),
            "sparse": [None if i > 5 else "val" for i in range(100)],
            "numeric": [None if i == 0 else float(i) for i in range(100)],
        }
    )
    p_path = tmp_path / "dataset.csv"
    df.to_csv(p_path, index=False)

    cleaned_df = clean(str(p_path), output=str(p_path))
    assert cleaned_df is not None

    # Verify atomic replacement and backup artifacts
    legacy_backup = tmp_path / "dataset.csv.zedda-backup"
    manifest_file = tmp_path / "dataset.csv.rollback.json"

    assert legacy_backup.exists()
    assert manifest_file.exists()

    with open(manifest_file, encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["status"] == "COMPLETE"
    assert manifest["target_file"] == "dataset.csv"
    assert len(manifest["actions"]) > 0


def test_clean_undo_restores_original(tmp_path):
    df = pd.DataFrame({"id": range(50), "sparse": [None] * 50, "feature": [1, 2] * 25})
    p_path = tmp_path / "target.csv"
    df.to_csv(p_path, index=False)

    clean(str(p_path), output=str(p_path))
    cleaned = pd.read_csv(p_path)
    assert "sparse" not in cleaned.columns
    assert "feature" in cleaned.columns

    undo_clean(str(p_path))
    restored = pd.read_csv(p_path)
    assert "sparse" in restored.columns


def test_clean_not_approved_returns_plan_without_mutation(tmp_path, monkeypatch):
    target = tmp_path / "not-approved.csv"
    target.write_text("id\n1\n", encoding="utf-8")
    before = target.read_bytes()

    profile = DatasetProfile(file_name=str(target), num_rows=1, num_cols=1, columns=[])
    monkeypatch.setattr("zedda._engine.scan", lambda *args, **kwargs: profile)

    result = clean(str(target), approved=False)

    assert isinstance(result, CleaningPlan)
    assert target.read_bytes() == before
    assert list(tmp_path.glob("*.backup*")) == []
    assert list(tmp_path.glob("*.rollback.json")) == []
    assert list(tmp_path.glob(".tmp_clean*")) == []


def test_clean_new_target_is_removed_when_manifest_fails(tmp_path):
    target = tmp_path / "new-target.csv"
    df = pd.DataFrame({"id": [1, 2, 3]})
    plan = CleaningPlan(proposed_changes=[], generated_from="test_plan")

    with (
        patch("json.dump", side_effect=OSError("manifest write failed")),
        pytest.raises(ZeddaError, match="manifest write failed"),
    ):
        execute_cleaning_transaction(
            df,
            plan,
            target_path=str(target),
            audit_actions=[],
            score_before=50,
            score_after=100,
        )

    assert not target.exists()


def test_clean_target_lock_rejects_concurrent_transaction(tmp_path):
    target = (tmp_path / "locked.csv").resolve()

    with (
        _target_lock(target),
        pytest.raises(ZeddaError, match="Another cleaning transaction"),
        _target_lock(target),
    ):
        pass
