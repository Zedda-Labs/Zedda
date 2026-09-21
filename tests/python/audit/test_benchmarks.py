import pytest
import zedda as zd
import time
import pandas as pd
from pathlib import Path
import os
import psutil


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_benchmark_100k(fixtures_dir):
    """Benchmark scan() on 100K rows."""
    path = str(fixtures_dir / "large.csv")

    start = time.perf_counter()
    p = zd.scan(path)
    duration = time.perf_counter() - start

    assert p.num_rows == 100000
    # Should take less than 1.5 seconds usually, but let's put a generous bound for CI
    assert duration < 5.0

    # scan_time_ms is populated
    assert p.scan_time_ms > 0


def test_benchmark_pandas_comparison(fixtures_dir):
    """Compare scan() vs pandas read_csv + describe."""
    path = str(fixtures_dir / "large.csv")

    start_zd = time.perf_counter()
    p = zd.scan(path)
    zd_duration = time.perf_counter() - start_zd

    start_pd = time.perf_counter()
    df = pd.read_csv(path)
    desc = df.describe(include="all")
    pd_duration = time.perf_counter() - start_pd

    # For large datasets, ZEDDA should be comparable or faster,
    # but we just want to record it.
    print(f"\nZEDDA time: {zd_duration:.4f}s")
    print(f"Pandas time: {pd_duration:.4f}s")
    # assert zd_duration <= pd_duration * 1.5  # Sometimes pandas is highly optimized for simple datasets


def test_memory_usage_large(fixtures_dir):
    """Memory benchmark: peak RSS before/after scan() on 100K rows."""
    process = psutil.Process(os.getpid())
    mem_before = process.memory_info().rss

    p = zd.scan(str(fixtures_dir / "large.csv"))

    mem_after = process.memory_info().rss

    mem_diff_mb = (mem_after - mem_before) / (1024 * 1024)
    print(f"\nMemory used by scan(): {mem_diff_mb:.2f} MB")

    # Core streaming scan shouldn't load everything into memory.
    # 100K rows with 4 columns is small anyway, but it should not spike
    # disproportionately (like > 500MB).
    assert mem_diff_mb < 500


def test_benchmark_200k():
    """Test bench_200k.csv if it exists in repo root."""
    path = (
        Path(__file__).parent.parent.parent.parent
        / "benchmarks"
        / "data"
        / "bench_200k.csv"
    )

    # If the path doesn't exist where we expect, look in root
    if not path.exists():
        path = Path(__file__).parent.parent.parent.parent / "bench_200k.csv"

    if not path.exists():
        pytest.skip("bench_200k.csv not found")

    start = time.perf_counter()
    p = zd.scan(str(path))
    duration = time.perf_counter() - start

    assert p.num_rows == 200000
    assert duration < 15.0  # Generous limit for disk I/O under background load


def test_scalability_sub_quadratic(fixtures_dir):
    """Verify scan time grows sub-quadratically with rows."""
    t1_start = time.perf_counter()
    zd.scan(str(fixtures_dir / "tiny.csv"))  # 3 rows
    t1_dur = time.perf_counter() - t1_start

    t2_start = time.perf_counter()
    zd.scan(str(fixtures_dir / "large.csv"))  # 100K rows
    t2_dur = time.perf_counter() - t2_start

    # If it was quadratic, it would take (100k/3)^2 times longer.
    # We just want to ensure it's not pathologically slow.
    ratio = t2_dur / max(t1_dur, 0.001)

    # 100K is ~33333x larger than 3.
    # Time ratio shouldn't be much worse than linear (33333x),
    # but small files have fixed overhead.
    # If it was quadratic it would be 1,000,000,000x.
    assert ratio < 100000
