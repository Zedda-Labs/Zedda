"""
Unit tests for zedda._scan module.

Tests count_lines() — the scan_arrow() function requires the C++ core
and pyarrow, so it's tested indirectly via the integration tests.

Run with: pytest tests/python/test_scan_module.py -v
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from zedda._scan import count_lines


class TestCountLines:
    """Tests for count_lines()."""

    def test_normal_file_with_trailing_newline(self, tmp_path):
        """File ending with newline: count = number of newlines."""
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n3,4\n")
        result = count_lines(str(f))
        assert result == 3  # 3 newlines

    def test_file_without_trailing_newline(self, tmp_path):
        """File without trailing newline: last row counted (M-8 fix)."""
        f = tmp_path / "data.csv"
        f.write_bytes(b"a,b\n1,2\n3,4")  # no trailing newline
        result = count_lines(str(f))
        assert result == 3  # 2 newlines + 1 for last row

    def test_single_line_no_newline(self, tmp_path):
        """Single line with no newline at all."""
        f = tmp_path / "data.csv"
        f.write_bytes(b"hello")
        result = count_lines(str(f))
        assert result == 1  # 0 newlines + 1 for the content

    def test_empty_file(self, tmp_path):
        """Empty file should return 0."""
        f = tmp_path / "empty.csv"
        f.write_text("")
        result = count_lines(str(f))
        assert result == 0

    def test_only_newlines(self, tmp_path):
        """File with only newlines should count them."""
        f = tmp_path / "newlines.csv"
        f.write_text("\n\n\n")
        result = count_lines(str(f))
        assert result == 3  # 3 newlines, no extra (last byte is \n)

    def test_large_file(self, tmp_path):
        """Large file should be counted correctly via chunked reads."""
        f = tmp_path / "large.csv"
        # Write 10000 lines
        content = "\n".join(f"row_{i}" for i in range(10000)) + "\n"
        f.write_text(content)
        result = count_lines(str(f))
        assert result == 10000

    def test_missing_file_returns_none(self):
        """Missing file should return None (not 0)."""
        result = count_lines("/nonexistent/path/file.csv")
        assert result is None

    def test_directory_returns_none(self, tmp_path):
        """A directory should return None (can't read as file)."""
        result = count_lines(str(tmp_path))
        assert result is None

    def test_binary_file_returns_none(self, tmp_path):
        """A binary file with null bytes should still count newlines."""
        f = tmp_path / "binary.csv"
        f.write_bytes(b"a\nb\x00c\nd\n")
        # Has 3 newlines — count_lines counts bytes, doesn't reject nulls
        result = count_lines(str(f))
        # The file has 3 newlines and ends with \n → 3
        assert result == 3

    def test_crlf_line_endings(self, tmp_path):
        """CRLF line endings: each \r\n counts as one line."""
        f = tmp_path / "crlf.csv"
        f.write_bytes(b"a,b\r\n1,2\r\n3,4\r\n")
        result = count_lines(str(f))
        # 3 newlines (\n), file ends with \n → 3
        assert result == 3

    def test_mixed_line_endings(self, tmp_path):
        """Mixed \n and \r\n should count correctly."""
        f = tmp_path / "mixed.csv"
        f.write_bytes(b"a\nb\r\nc\nd")
        result = count_lines(str(f))
        # 3 newlines (\n), no trailing newline → 3 + 1 = 4
        assert result == 4
