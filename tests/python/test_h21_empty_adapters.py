from __future__ import annotations

import pandas as pd
import pytest
import zedda as zd

pa = pytest.importorskip("pyarrow")
ipc = pytest.importorskip("pyarrow.ipc")
feather = pytest.importorskip("pyarrow.feather")


def _assert_empty_profile(profile):
    assert profile.num_rows == 0
    assert [column.name for column in profile.columns] == ["id", "label"]
    assert [column.type_str for column in profile.columns] == ["int", "str"]


def test_empty_dataframe_preserves_schema():
    frame = pd.DataFrame(
        {
            "id": pd.Series([], dtype="int64"),
            "label": pd.Series([], dtype="string"),
        }
    )

    _assert_empty_profile(zd.scan(frame))


def test_empty_arrow_ipc_preserves_schema(tmp_path):
    table = pa.table(
        {
            "id": pa.array([], type=pa.int64()),
            "label": pa.array([], type=pa.string()),
        }
    )
    path = tmp_path / "empty.arrow"
    with pa.OSFile(str(path), "wb") as sink, ipc.new_file(sink, table.schema):
        pass

    _assert_empty_profile(zd.scan(str(path)))


def test_empty_feather_preserves_schema(tmp_path):
    table = pa.table(
        {
            "id": pa.array([], type=pa.int64()),
            "label": pa.array([], type=pa.string()),
        }
    )
    path = tmp_path / "empty.feather"
    feather.write_feather(table, str(path))

    _assert_empty_profile(zd.scan(str(path)))
