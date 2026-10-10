import pathlib, tempfile, zedda as zd

def test_m5_exact_int64_single_thread(tmp_path):
    vals = [9007199254740993, 9007199254740995, 4611686018427387905]
    p = tmp_path / "forced_single.csv"
    p.write_text("x,note\n" + "\n".join(f'{v},"l1\nl2"' for v in vals) + "\n")
    c = zd.scan(str(p)).columns[0]
    
    assert c.is_pure_int64
    assert c.exact_int_min == min(vals)
    assert c.exact_int_max == max(vals)
    assert c.exact_int_sum == sum(vals)
    assert getattr(c, "exact_numeric_overflowed", False) is False

def test_m5_uint64_overflow_reports_none(tmp_path):
    vals2 = [18446744073709551615, 9223372036854775808]
    p2 = tmp_path / "uint64_test.csv"
    p2.write_text("x,note\n" + "\n".join(f'{v},"l1\nl2"' for v in vals2) + "\n")
    c2 = zd.scan(str(p2)).columns[0]
    
    assert getattr(c2, "exact_numeric_overflowed", False) is True
    # Values should be None when overflowed
    assert c2.exact_int_min is None
    assert c2.exact_int_max is None
    assert c2.exact_int_sum is None
