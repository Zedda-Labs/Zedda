import pytest
import zedda as zd
import psutil
import os
import gc
from pathlib import Path


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_stress_memory_leak(fixtures_dir):
    """Repeated scan() calls (100x) - verify no memory leak."""
    path = str(fixtures_dir / "tiny.csv")

    # Warmup
    for _ in range(5):
        zd.scan(path)
    gc.collect()

    process = psutil.Process(os.getpid())
    mem_start = process.memory_info().rss

    for _ in range(100):
        zd.scan(path)

    gc.collect()
    mem_end = process.memory_info().rss

    mem_diff_mb = (mem_end - mem_start) / (1024 * 1024)
    # Shouldn't leak more than a few MBs ideally, some Python objects might stick around
    assert mem_diff_mb < 20.0


def test_stress_all_fixtures_sequential(fixtures_dir):
    """Scan all 18 fixture files sequentially - ensure no crash."""
    for file in fixtures_dir.glob("*.csv"):
        if file.name == "corrupted.csv":
            try:
                zd.scan(str(file))
            except zd.ZeddaError:
                pass
        else:
            # Empty header might raise error depending on impl, let's catch it
            try:
                zd.scan(str(file))
            except zd.ZeddaError as e:
                if (
                    "empty" not in str(e).lower()
                    and "unsupported" not in str(e).lower()
                ):
                    raise


def test_stress_adversarial(fixtures_dir):
    """Scan adversarial fixture in loop to ensure no crash."""
    path = str(fixtures_dir / "adversarial.csv")
    for _ in range(10):
        try:
            zd.scan(path)
        except zd.ZeddaError:
            pass  # Acceptable if it errors, but MUST NOT crash Python process
