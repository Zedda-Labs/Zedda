import os
import tempfile
import pytest
from pathlib import Path

import zedda as zd
from zedda import ZeddaError

def test_csv_works_without_pyarrow():
    """Verify that CSV profiling succeeds even if pyarrow is missing."""
    # We can't strictly force pyarrow to be missing here if it's installed in the env,
    # but the CI job `test-python-no-extras` runs this file in an environment
    # where pyarrow is NOT installed.

    csv_content = "A,B\n1,2\n3,4\n"
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        f.write(csv_content)
        temp_csv = f.name

    try:
        # This should succeed regardless of whether pyarrow is installed
        p = zd.scan(temp_csv)
        assert p.num_rows == 2
        assert p.num_cols == 2
    finally:
        os.unlink(temp_csv)

def test_parquet_raises_correct_error_without_pyarrow():
    """Verify that using Parquet raises ZeddaError when pyarrow is missing."""
    try:
        import pyarrow
        pytest.skip("pyarrow is installed, cannot test optional error path")
    except ImportError:
        pass

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        temp_parquet = f.name

    try:
        with pytest.raises(ZeddaError, match=r"Parquet/Arrow support requires pyarrow.*pip install zedda\[parquet\]"):
            zd.scan(temp_parquet)
    finally:
        os.unlink(temp_parquet)
