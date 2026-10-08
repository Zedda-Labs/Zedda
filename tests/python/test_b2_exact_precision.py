import pytest
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import zedda as zd

BIG_INT_1 = 9007199254740993       # 2^53 + 1 (cannot be represented exactly in IEEE 754 double)
BIG_INT_2 = 9223372036854775000     # Near INT64_MAX
SMALL_INT = 100

def test_parquet_exact_int64(tmp_path):
    pfile = tmp_path / "exact_parquet.parquet"
    table = pa.table({"val": pa.array([SMALL_INT, BIG_INT_1], type=pa.int64())})
    pq.write_table(table, str(pfile))
    
    profile = zd.scan(str(pfile))
    col = profile.columns[0]
    
    expected_min = SMALL_INT
    expected_max = BIG_INT_1
    expected_sum = SMALL_INT + BIG_INT_1
    
    assert col.val_min == expected_min, f"min mismatch: {col.val_min} != {expected_min}"
    assert isinstance(col.val_min, int), f"min not int: {type(col.val_min)}"
    assert col.val_max == expected_max, f"max mismatch: {col.val_max} != {expected_max}"
    assert isinstance(col.val_max, int), f"max not int: {type(col.val_max)}"
    assert col.sum == expected_sum, f"sum mismatch: {col.sum} != {expected_sum}"
    assert isinstance(col.sum, int), f"sum not int: {type(col.sum)}"
    assert col.is_pure_int64 is True
    assert col.exact_int_sum == expected_sum
    assert col.exact_int_min == expected_min
    assert col.exact_int_max == expected_max

def test_csv_multithread_exact_int64(tmp_path):
    # Force multithread path: file size >= 16384 bytes without embedded newlines
    cfile = tmp_path / "exact_multithread.csv"
    lines = ["val\n", f"{SMALL_INT}\n", f"{BIG_INT_1}\n"]
    # Pad to exceed 16KB with valid ints
    pad_line = "100\n"
    # 16384 bytes / 4 bytes per line = ~4100 lines
    for _ in range(4500):
        lines.append(pad_line)
    cfile.write_text("".join(lines), encoding="utf-8")
    assert cfile.stat().st_size >= 16384, f"File size too small: {cfile.stat().st_size}"
    
    profile = zd.scan(str(cfile))
    col = profile.columns[0]
    
    expected_min = SMALL_INT
    expected_max = BIG_INT_1
    expected_sum = SMALL_INT + BIG_INT_1 + (4500 * 100)
    
    assert col.val_min == expected_min, f"min mismatch: {col.val_min} != {expected_min}"
    assert isinstance(col.val_min, int), f"min not int: {type(col.val_min)}"
    assert col.val_max == expected_max, f"max mismatch: {col.val_max} != {expected_max}"
    assert isinstance(col.val_max, int), f"max not int: {type(col.val_max)}"
    assert col.sum == expected_sum, f"sum mismatch: {col.sum} != {expected_sum}"
    assert isinstance(col.sum, int), f"sum not int: {type(col.sum)}"
    assert col.is_pure_int64 is True
    assert col.exact_int_sum == expected_sum
    assert col.exact_int_min == expected_min
    assert col.exact_int_max == expected_max

def test_csv_mmap_singlethread_exact_int64(tmp_path):
    # Force single-thread mmap path: file size < 16384 bytes
    cfile = tmp_path / "exact_mmap_small.csv"
    cfile.write_text(f"val\n{SMALL_INT}\n{BIG_INT_1}\n", encoding="utf-8")
    assert cfile.stat().st_size < 16384, f"File size not small: {cfile.stat().st_size}"
    
    profile = zd.scan(str(cfile))
    col = profile.columns[0]
    
    expected_min = SMALL_INT
    expected_max = BIG_INT_1
    expected_sum = SMALL_INT + BIG_INT_1
    
    assert col.val_min == expected_min, f"min mismatch: {col.val_min} != {expected_min}"
    assert isinstance(col.val_min, int), f"min not int: {type(col.val_min)}"
    assert col.val_max == expected_max, f"max mismatch: {col.val_max} != {expected_max}"
    assert isinstance(col.val_max, int), f"max not int: {type(col.val_max)}"
    assert col.sum == expected_sum, f"sum mismatch: {col.sum} != {expected_sum}"
    assert isinstance(col.sum, int), f"sum not int: {type(col.sum)}"
    assert col.is_pure_int64 is True
    assert col.exact_int_sum == expected_sum
    assert col.exact_int_min == expected_min
    assert col.exact_int_max == expected_max

def test_csv_fallback_singlethread_embedded_newlines_exact_int64(tmp_path):
    # Force single-thread fallback path: file size >= 16384 bytes with embedded newline
    cfile = tmp_path / "exact_fallback.csv"
    # Row with embedded newline forces num_threads = 1
    lines = ["id,val\n", '1,"note\nwith newline"\n', f"2,{BIG_INT_1}\n", f"3,{SMALL_INT}\n"]
    for i in range(4, 3000):
        lines.append(f"{i},100\n")
    cfile.write_text("".join(lines), encoding="utf-8")
    assert cfile.stat().st_size >= 16384, f"File size too small: {cfile.stat().st_size}"
    
    profile = zd.scan(str(cfile))
    col = profile.columns[1]  # "val" column
    
    expected_min = SMALL_INT
    expected_max = BIG_INT_1
    expected_sum = BIG_INT_1 + SMALL_INT + ((3000 - 4) * 100)
    
    assert col.val_min == expected_min, f"min mismatch: {col.val_min} != {expected_min}"
    assert isinstance(col.val_min, int), f"min not int: {type(col.val_min)}"
    assert col.val_max == expected_max, f"max mismatch: {col.val_max} != {expected_max}"
    assert isinstance(col.val_max, int), f"max not int: {type(col.val_max)}"
    assert col.sum == expected_sum, f"sum mismatch: {col.sum} != {expected_sum}"
    assert isinstance(col.sum, int), f"sum not int: {type(col.sum)}"
    assert col.is_pure_int64 is True
    assert col.exact_int_sum == expected_sum
    assert col.exact_int_min == expected_min
    assert col.exact_int_max == expected_max
