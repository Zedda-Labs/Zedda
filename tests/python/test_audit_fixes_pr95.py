import collections
import json
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.abspath("build/Release"))
sys.path.insert(0, os.path.abspath("python"))

import pandas as pd
import zedda as zd
from zedda import fasteda_core as _core
from zedda._adapters.csv_adapter import CSVAdapter


def test_large_integers_precision():
    """Verify that integers >= 2^53, INT64_MAX, INT64_MIN, UINT64_MAX remain exact."""
    val_2_53_plus_1 = 9007199254740993
    val_int64_max = 9223372036854775807
    val_int64_min = -9223372036854775808
    val_uint64_max = 18446744073709551615

    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
        f.write("id,bignum\n")
        f.write(f"1,{val_2_53_plus_1}\n")
        f.write(f"2,{val_int64_max}\n")
        f.write(f"3,{val_int64_min}\n")
        f.write(f"4,{val_uint64_max}\n")
        temp_csv = f.name

    try:
        p = zd.scan(temp_csv)
        bignum_col = next(c for c in p.columns if c.name == "bignum")
        assert bignum_col.type_str in ("int", "INTEGER")
        assert bignum_col.valid_count == 4
        assert bignum_col.unique_exact == 4

        # Verify top_values contain exact string representations
        top_vals = [
            tv.value if hasattr(tv, "value") else str(tv)
            for tv in bignum_col.top_values
        ]
        assert str(val_2_53_plus_1) in top_vals
        assert str(val_int64_max) in top_vals
        assert str(val_int64_min) in top_vals
        assert str(val_uint64_max) in top_vals
    finally:
        if os.path.exists(temp_csv):
            os.remove(temp_csv)


def test_integer_sum_overflow_distinct_count():
    """Verify that arithmetic sum overflow does not break unique/distinct count or type purity."""
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
        f.write("val\n")
        for _ in range(10):
            f.write("9000000000000000000\n")
        f.write("1\n")
        temp_csv = f.name

    try:
        p = zd.scan(temp_csv)
        col = p.columns[0]
        assert col.valid_count == 11
        assert col.unique_exact == 2
        assert col.type_str in ("int", "INTEGER")
    finally:
        if os.path.exists(temp_csv):
            os.remove(temp_csv)


def test_json_null_vs_real_zero():
    """Verify Profile serialization distinguishes real zero from missing/null metrics."""
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
        f.write("zeros,words\n")
        f.write("0,apple\n")
        f.write("0,banana\n")
        f.write("0,cherry\n")
        temp_csv = f.name

    try:
        # C++ native JSON serialization
        cpp_prof = _core.profile(
            temp_csv, False, False, 1000000, False, ord(","), ord('"'), 0, "utf-8"
        )
        cpp_json = json.loads(cpp_prof.to_json())

        zeros_cpp = next(c for c in cpp_json["columns"] if c["name"] == "zeros")
        words_cpp = next(c for c in cpp_json["columns"] if c["name"] == "words")

        assert zeros_cpp["mean"] == 0.0
        assert zeros_cpp["val_min"] == 0.0
        assert zeros_cpp["val_max"] == 0.0

        assert words_cpp["mean"] is None
        assert words_cpp["std"] is None
        assert words_cpp["val_min"] is None
        assert words_cpp["val_max"] is None

        # Python Profile model properties
        p = zd.scan(temp_csv)
        zeros_col = next(c for c in p.columns if c.name == "zeros")
        words_col = next(c for c in p.columns if c.name == "words")

        assert zeros_col.mean == 0.0
        assert zeros_col.val_min == 0.0
        assert zeros_col.val_max == 0.0

        assert words_col.mean is None
        assert words_col.std is None
        assert words_col.val_min is None
        assert words_col.val_max is None
    finally:
        if os.path.exists(temp_csv):
            os.remove(temp_csv)


def test_reservoir_sampling_merge_small_and_large():
    """Verify reservoir sampling on small, equal, and large datasets."""
    # Small dataset (< 512 rows)
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
        f.write("idx\n")
        for i in range(100):
            f.write(f"{i}\n")
        small_csv = f.name

    # Equal dataset (512 rows)
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
        f.write("idx\n")
        for i in range(512):
            f.write(f"{i}\n")
        eq_csv = f.name

    # Large dataset (> 512 rows)
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
        f.write("idx\n")
        for i in range(2000):
            f.write(f"{i}\n")
        large_csv = f.name

    try:
        p_small = zd.scan(small_csv)
        assert p_small.columns[0].valid_count == 100

        p_eq = zd.scan(eq_csv)
        assert p_eq.columns[0].valid_count == 512

        p_large = zd.scan(large_csv)
        assert p_large.columns[0].valid_count == 2000
    finally:
        for path in [small_csv, eq_csv, large_csv]:
            if os.path.exists(path):
                os.remove(path)


def test_csv_dialect_cache_invalidation_and_bounding():
    """Verify CSV dialect cache invalidation on file modification and bounding behavior."""
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
        f.write("a,b,c\n1,2,3\n")
        temp_csv = f.name

    try:
        p1 = zd.scan(temp_csv)
        assert len(p1.columns) == 3

        with open(temp_csv, "w", newline="") as f:
            f.write("x;y;z;w\n10;20;30;40\n")

        p2 = zd.scan(temp_csv)
        assert len(p2.columns) == 4

        for i in range(600):
            fake_key = (f"/fake/path_{i}.csv", 1000 + i, 100, None)
            with CSVAdapter._dialect_lock:
                CSVAdapter._dialect_cache[fake_key] = ("utf-8", ",", '"', "\0")
                if len(CSVAdapter._dialect_cache) > CSVAdapter._MAX_DIALECT_CACHE:
                    CSVAdapter._dialect_cache.popitem(last=False)

        with CSVAdapter._dialect_lock:
            assert len(CSVAdapter._dialect_cache) <= CSVAdapter._MAX_DIALECT_CACHE
    finally:
        if os.path.exists(temp_csv):
            os.remove(temp_csv)


def test_arrow_repeated_lifecycle():
    """Verify repeated creation and destruction of Arrow-backed profiles (no leaks/crashes)."""
    df = pd.DataFrame(
        {
            "int_col": [1, 2, 3, 4, 5],
            "str_col": ["a", "b", "c", "d", "e"],
            "flt_col": [1.1, 2.2, 3.3, 4.4, 5.5],
        }
    )

    for _ in range(50):
        p = zd.scan(df)
        assert p.num_rows == 5
        assert p.num_cols == 3
