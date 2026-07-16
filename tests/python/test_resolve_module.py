"""
Unit tests for zedda._resolve module.

Tests resolve_input(), write_temp_arrow(), cleanup_temp(), and
require_pyarrow() without needing the C++ core.

Run with: pytest tests/python/test_resolve_module.py -v
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from zedda._resolve import (
    ZeddaError,
    resolve_input,
    cleanup_temp,
    require_pyarrow,
)


class TestResolveInput:
    """Tests for resolve_input()."""

    def test_string_path_passthrough(self):
        """A string path should pass through unchanged."""
        result, is_temp = resolve_input("/data/test.csv")
        assert result == "/data/test.csv"
        assert is_temp is False

    def test_path_object_passthrough(self):
        """A Path object should convert to string and pass through."""
        result, is_temp = resolve_input(Path("/data/test.csv"))
        assert result == "/data/test.csv"
        assert is_temp is False

    def test_pandas_dataframe_creates_temp(self):
        """A pandas DataFrame should create a temp parquet file."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            pytest.skip("pyarrow not installed")
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        result, is_temp = resolve_input(df)
        assert is_temp is True
        assert result.endswith(".parquet")
        assert os.path.exists(result)
        # Cleanup
        cleanup_temp(result)
        assert not os.path.exists(result)

    def test_polars_dataframe_creates_temp(self):
        """A polars DataFrame should create a temp parquet file."""
        try:
            import polars as pl
        except ImportError:
            pytest.skip("polars not installed")
        df = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        result, is_temp = resolve_input(df)
        assert is_temp is True
        assert result.endswith(".parquet")
        assert os.path.exists(result)
        cleanup_temp(result)

    def test_unsupported_type_raises(self):
        """An unsupported input type should raise ZeddaError."""
        with pytest.raises(ZeddaError, match="Unsupported input type"):
            resolve_input(42)

    def test_unsupported_type_list_raises(self):
        """A list should raise ZeddaError."""
        with pytest.raises(ZeddaError, match="Unsupported input type"):
            resolve_input([1, 2, 3])

    def test_unsupported_type_dict_raises(self):
        """A dict should raise ZeddaError."""
        with pytest.raises(ZeddaError, match="Unsupported input type"):
            resolve_input({"a": 1})


class TestCleanupTemp:
    """Tests for cleanup_temp()."""

    def test_cleanup_existing_file(self, tmp_path):
        """cleanup_temp should delete an existing file."""
        f = tmp_path / "temp.csv"
        f.write_text("data")
        assert f.exists()
        cleanup_temp(str(f))
        assert not f.exists()

    def test_cleanup_nonexistent_file_silent(self):
        """cleanup_temp should not raise for a nonexistent file."""
        # Should not raise OSError
        cleanup_temp("/nonexistent/path/file.csv")

    def test_cleanup_after_resolve(self):
        """cleanup_temp should work after resolve_input creates a temp."""
        try:
            import pandas as pd
            import pyarrow  # noqa: F401
        except ImportError:
            pytest.skip("pandas/pyarrow not installed")
        df = pd.DataFrame({"a": [1, 2]})
        path, is_temp = resolve_input(df)
        assert is_temp
        assert os.path.exists(path)
        cleanup_temp(path)
        assert not os.path.exists(path)


class TestRequirePyarrow:
    """Tests for require_pyarrow()."""

    def test_require_pyarrow_available(self):
        """If pyarrow is installed, require_pyarrow() should not raise."""
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            pytest.skip("pyarrow not installed")
        # Should not raise
        require_pyarrow()

    def test_require_pyarrow_missing_raises(self, monkeypatch):
        """If pyarrow is not installed, require_pyarrow() should raise ZeddaError."""
        # Simulate pyarrow not being importable
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name.startswith("pyarrow"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(ZeddaError, match="Parquet/Arrow support requires pyarrow"):
            require_pyarrow()
