import pytest
import zedda as zd
import pandas as pd
import tempfile
import os
from pathlib import Path
from zedda._errors import ZeddaError


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_format_csv(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "tiny.csv"))
    assert p.num_rows == 3


def test_format_parquet(fixtures_dir):
    pq_file = fixtures_dir / "normal_business.parquet"
    if not pq_file.exists():
        pytest.skip("Parquet fixture not generated")

    p = zd.scan(str(pq_file))
    assert p.num_rows == 500


def test_format_dataframe():
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    p = zd.scan(df)
    assert p.num_rows == 2
    assert p.num_cols == 2


def test_format_arrow_ipc():
    import pyarrow as pa
    import pyarrow.ipc as ipc

    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    table = pa.Table.from_pandas(df)

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test.arrow")
        with (
            pa.OSFile(path, "wb") as sink,
            ipc.new_file(sink, table.schema) as writer,
        ):
            writer.write_table(table)

        p = zd.scan(path)
        assert p.num_rows == 2


def test_format_feather():
    import pyarrow.feather as feather

    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test.feather")
        feather.write_feather(df, path)

        p = zd.scan(path)
        assert p.num_rows == 2


def test_format_empty_file():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "empty.csv")
        open(path, "w").close()

        with pytest.raises(ZeddaError, match="empty"):
            zd.scan(path)


def test_format_malformed_csv():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "malformed.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("col1,col2\n")
            f.write("1,2\n")
            # unterminated quote
            f.write('3,"abc\n')

        # ZEDDA is robust to some malformed CSVs, but if it fails it should raise ZeddaError, not crash
        try:
            zd.scan(path)
        except ZeddaError:
            pass


def test_format_polars_dataframe():
    try:
        import polars as pl

        df = pl.DataFrame({"a": [1, 2], "b": [3, 4]})
        p = zd.scan(df)
        assert p.num_rows == 2
    except ImportError:
        pytest.skip("Polars not installed")
