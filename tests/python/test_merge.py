import pytest
import pandas as pd
import zedda as zd


def test_merge_basic(tmp_path):
    df1 = pd.DataFrame({"id": [1, 2], "v1": [10, 20]})
    df2 = pd.DataFrame({"id": [1, 2], "v2": [100, 200]})

    p1 = tmp_path / "1.csv"
    p2 = tmp_path / "2.csv"
    df1.to_csv(p1, index=False)
    df2.to_csv(p2, index=False)

    merged = zd.merge([str(p1), str(p2)])
    assert "v1" in merged.columns
    assert "v2" in merged.columns
    assert len(merged) == 4


def test_merge_dataframes():
    df1 = pd.DataFrame({"id": [1, 2], "v1": [10, 20]})
    df2 = pd.DataFrame({"id": [1, 2], "v2": [100, 200]})

    merged = zd.merge([df1, df2])
    assert "v1" in merged.columns
    assert "v2" in merged.columns
    assert len(merged) == 4


def test_merge_canonical_module():
    from zedda._merge import merge as _merge_fn

    assert zd.merge is _merge_fn


def test_merge_validation_errors():
    with pytest.raises(zd.ZeddaError, match="at least 2 file paths"):
        zd.merge(["single_file.csv"])


def test_merge_dedup_and_provenance(tmp_path):
    df1 = pd.DataFrame({"id": [1, 2], "val": [10, 20]})
    df2 = pd.DataFrame({"id": [2, 3], "val": [20, 30]})

    p1 = tmp_path / "a.csv"
    p2 = tmp_path / "b.csv"
    df1.to_csv(p1, index=False)
    df2.to_csv(p2, index=False)

    out = tmp_path / "out.csv"
    merged = zd.merge([str(p1), str(p2)], output=str(out))

    assert "zedda_source_file" in merged.columns
    # Row with id=2, val=20 is deduplicated (3 unique rows)
    assert len(merged) == 3
    assert out.exists()


def test_merge_schema_policies(tmp_path):
    df1 = pd.DataFrame({"id": [1, 2], "v1": [10, 20]})
    df2 = pd.DataFrame({"id": [3, 4], "v2": [100, 200]})

    p1 = tmp_path / "pol1.csv"
    p2 = tmp_path / "pol2.csv"
    df1.to_csv(p1, index=False)
    df2.to_csv(p2, index=False)

    # strict mode raises ZeddaError on schema mismatch
    with pytest.raises(zd.ZeddaError, match="Schema mismatch"):
        zd.merge([str(p1), str(p2)], policy="strict")

    # intersection mode retains only common columns (id)
    merged_inter = zd.merge([str(p1), str(p2)], policy="intersection")
    assert "id" in merged_inter.columns
    assert "v1" not in merged_inter.columns
    assert "v2" not in merged_inter.columns

    # union mode retains all columns
    merged_union = zd.merge([str(p1), str(p2)], policy="union")
    assert "v1" in merged_union.columns
    assert "v2" in merged_union.columns


def test_merge_dedup_flag(tmp_path):
    df1 = pd.DataFrame({"id": [1, 2], "val": [10, 20]})
    df2 = pd.DataFrame({"id": [2, 3], "val": [20, 30]})

    p1 = tmp_path / "d1.csv"
    p2 = tmp_path / "d2.csv"
    df1.to_csv(p1, index=False)
    df2.to_csv(p2, index=False)

    # dedup=False keeps duplicate rows (4 total)
    merged_no_dedup = zd.merge([str(p1), str(p2)], dedup=False)
    assert len(merged_no_dedup) == 4


def test_merge_fail_closed_unreadable(tmp_path):
    df1 = pd.DataFrame({"id": [1, 2], "val": [10, 20]})
    p1 = tmp_path / "valid.csv"
    df1.to_csv(p1, index=False)
    p_nonexistent = tmp_path / "does_not_exist.csv"

    # Missing/unreadable input must raise ZeddaError when strict=True
    with pytest.raises(zd.ZeddaError, match="Failed to"):
        zd.merge([str(p1), str(p_nonexistent)], strict=True)

    # All-input failure must always raise ZeddaError
    p_nonexistent2 = tmp_path / "does_not_exist2.csv"
    with pytest.raises(zd.ZeddaError, match="All input files failed to load"):
        zd.merge([str(p_nonexistent), str(p_nonexistent2)])


