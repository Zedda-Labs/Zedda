import os
from pathlib import Path
import pytest
import zedda as zd
from zedda._errors import ZeddaError
import pandas as pd
import numpy as np


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_scan_tiny(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "tiny.csv"))
    assert p.num_rows == 3
    assert p.num_cols == 3
    assert p.columns[0].name == "id"
    assert p.columns[1].name == "name"
    assert p.columns[2].name == "score"
    assert p.columns[0].type_str == "int"
    assert p.columns[1].type_str == "str"
    assert p.columns[2].type_str == "float"


def test_scan_normal(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "normal_business.csv"))
    assert p.num_rows == 500
    assert p.num_cols == 5
    assert p.columns[0].val_min == 1000
    assert p.columns[0].val_max == 1499


def test_scan_large(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "large.csv"))
    assert p.num_rows == 100000
    assert p.num_cols == 4
    assert p.columns[0].val_min == 0
    assert p.columns[0].val_max == 99999


def test_scan_wide(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "wide.csv"))
    assert p.num_rows == 5
    assert p.num_cols == 200


def test_scan_tall(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "tall.csv"))
    assert p.num_rows == 500000
    assert p.num_cols == 3


def test_scan_mostly_null(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "mostly_null.csv"))
    assert p.num_rows == 100
    assert p.num_cols == 3
    for col in p.columns:
        assert col.null_pct > 70.0
        assert col.has_high_nulls


def test_scan_duplicates(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "duplicates.csv"))
    assert p.num_rows == 100
    assert p.columns[0].unique_approx <= 40


def test_scan_high_cardinality(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "high_cardinality.csv"))
    uuid_col = [c for c in p.columns if c.name == "uuid"][0]
    assert uuid_col.is_high_cardinality


def test_scan_mixed_types(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "mixed_types.csv"))
    types = {c.name: c.type_str for c in p.columns}
    assert types["int_col"] == "int"
    assert types["float_col"] == "float"
    assert types["str_col"] == "str"
    assert types["bool_col"] == "bool"
    # Date parsing logic could classify date as str depending on ZEDDA implementation
    assert types["date_col"] in ("str", "date", "datetime")


def test_scan_numeric_only(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "numeric_only.csv"))
    assert p.num_cols == 3
    for c in p.columns:
        assert c.type_str in ("int", "float")


def test_scan_string_only(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "string_only.csv"))
    assert p.num_cols == 2
    for c in p.columns:
        assert c.type_str == "str"


def test_scan_datetime(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "datetime.csv"))
    assert p.num_rows == 3


def test_scan_unicode(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "unicode.csv"))
    assert p.num_rows == 2


def test_scan_dirty_realworld(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "dirty_realworld.csv"))
    assert p.num_rows == 10


def test_scan_adversarial(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "adversarial.csv"))
    assert p.num_rows == 4


def test_scan_corrupted(fixtures_dir):
    with pytest.raises(ZeddaError):
        zd.scan(str(fixtures_dir / "corrupted.csv"))


def test_scan_empty_header(fixtures_dir):
    # Depending on implementation, empty data might raise an error or return 0 rows.
    try:
        p = zd.scan(str(fixtures_dir / "empty_header.csv"))
        assert p.num_rows == 0
    except ZeddaError as e:
        assert "empty" in str(e).lower() or "no data" in str(e).lower()


def test_scan_unsupported_format(tmp_path):
    f = tmp_path / "test.xyz"
    f.write_text("a,b,c")
    with pytest.raises(ZeddaError, match="Unsupported file format"):
        zd.scan(str(f))


def test_scan_sample_size(fixtures_dir):
    p = zd.scan(str(fixtures_dir / "normal_business.csv"), sample_size=100)
    assert p.num_rows == 100
    assert p.is_sampled


def test_scan_invalid_sample_size(fixtures_dir):
    with pytest.raises(ValueError):
        zd.scan(str(fixtures_dir / "normal_business.csv"), sample_size=0)
    with pytest.raises(ValueError):
        zd.scan(str(fixtures_dir / "normal_business.csv"), sample_size=-100)
