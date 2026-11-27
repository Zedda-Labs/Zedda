import zedda as zd
from zedda._models import MetricStatus


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


def test_uint64_overflow_probe(tmp_path):
    p = tmp_path / "probe.csv"
    p.write_text("x\n18446744073709551615\n9223372036854775808\n5\n")
    c = zd.scan(str(p)).columns[0]

    # Expect min=5
    assert c.val_min == 5
    assert c.min == 5

    # is_pure_int64 False when overflowed
    assert c.is_pure_int64 is False

    # no float-rounded value shown as exact
    assert c.metrics["min"].status == MetricStatus.APPROXIMATE
    assert c.metrics["max"].status == MetricStatus.APPROXIMATE
    assert c.metrics["mean"].status == MetricStatus.APPROXIMATE
    # distinct/uniqueness tracking stays exact
    assert c.metrics["unique"].status == MetricStatus.EXACT
    assert c.unique_exact == 3
    assert c.distinct_overflowed is False
    assert "18446744073709551615" in c.top_values

    # sum reported non-exact, not silently None
    assert c.sum is not None
    assert isinstance(c.sum, float)
    assert c.exact_int_sum is None
    assert c.sum > 0
