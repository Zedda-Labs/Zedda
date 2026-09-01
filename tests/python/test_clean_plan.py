import pytest
import pandas as pd
import zedda as zd
from zedda._models import CleaningPlan, Change


def test_clean_plan_pure_generator(tmp_path):
    df = pd.DataFrame(
        {
            "id": range(100),
            "sparse_text": [None if i > 10 else "text" for i in range(100)],
            "numeric_nulls": [None if i % 10 == 0 else float(i) for i in range(100)],
            "constant_col": [1] * 100,
        }
    )
    p_path = tmp_path / "test.csv"
    df.to_csv(p_path, index=False)

    # Calling clean with dry_run=True returns a CleaningPlan without writing changes
    plan = zd.clean(str(p_path), dry_run=True)
    assert isinstance(plan, CleaningPlan)
    assert plan.dry_run is True
    assert plan.requires_approval is True
    assert len(plan.proposed_changes) > 0

    # Ensure every change cites concrete rationale
    for change in plan.proposed_changes:
        assert isinstance(change, Change)
        assert change.column in df.columns
        assert change.operation in ("drop", "impute", "encode", "clip")
        assert len(change.rationale) > 0


def test_clean_plan_no_io_side_effects(tmp_path):
    df = pd.DataFrame({"id": range(50), "constant": [42] * 50})
    p_path = tmp_path / "immutable.csv"
    df.to_csv(p_path, index=False)

    mtime_before = p_path.stat().st_mtime
    plan = zd.clean(str(p_path), dry_run=True)

    # File must be untouched
    assert p_path.stat().st_mtime == mtime_before
    assert not (tmp_path / "immutable.csv.zedda-backup").exists()
    assert not (tmp_path / "immutable.csv.rollback.json").exists()
