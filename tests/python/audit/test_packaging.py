import pytest
import subprocess
import zedda as zd
import os
from pathlib import Path


def test_packaging_version():
    assert zd.__version__ == "0.4.9"


def test_packaging_cli_entry_point():
    # Should be able to call python -m zedda --help
    result = subprocess.run(
        ["python", "-m", "zedda", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "Usage: " in result.stdout


def test_packaging_fasteda_core():
    # Should be able to import the native module
    try:
        from zedda import fasteda_core
    except ImportError:
        pytest.fail("fasteda_core native extension is not available!")


def test_packaging_pyproject_toml():
    pyproject_path = Path(__file__).parent.parent.parent.parent / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(encoding="utf-8")
        assert 'name = "zedda"' in content
        assert 'dynamic = ["version"]' in content
        assert "scikit-build-core" in content
