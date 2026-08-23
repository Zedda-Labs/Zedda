import json
import pytest
import pandas as pd
import zedda as zd
from zedda._clean import clean, undo_clean
from zedda._clean_executor import execute_cleaning_transaction
from zedda._models import CleaningPlan, CleanExecutionStatus


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

    with open(manifest_file, "r", encoding="utf-8") as f:
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
