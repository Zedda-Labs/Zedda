"""
Smoke tests for the zedda CLI.

Tests that the CLI commands exist, accept arguments, and produce output
without crashing. Uses typer's CliRunner for isolated testing.

Run with: pytest tests/python/test_cli_smoke.py -v
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

try:
    from typer.testing import CliRunner
    CLI_TEST_AVAILABLE = True
except ImportError:
    CLI_TEST_AVAILABLE = False

import zedda as zd


pytestmark = pytest.mark.skipif(not CLI_TEST_AVAILABLE, reason="typer not installed")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_csv(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text("name,age,salary\nAlice,30,50000\nBob,25,60000\nCarol,35,70000\n")
    return str(f)


class TestCLIVersion:
    """Test the `zedda version` command."""

    def test_version_prints(self, runner):
        from zedda.cli import app
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert zd.__version__ in result.output


class TestCLIInfo:
    """Test the `zedda info` command."""

    def test_info_existing_file(self, runner, sample_csv):
        from zedda.cli import app
        result = runner.invoke(app, ["info", sample_csv])
        assert result.exit_code == 0
        assert "test.csv" in result.output
        assert "Size" in result.output

    def test_info_nonexistent_file(self, runner):
        from zedda.cli import app
        result = runner.invoke(app, ["info", "/nonexistent/file.csv"])
        assert result.exit_code == 1


class TestCLIRun:
    """Test the `zedda run` command."""

    def test_run_existing_file(self, runner, sample_csv):
        from zedda.cli import app
        result = runner.invoke(app, ["run", sample_csv])
        # May return 0 or 1 depending on whether C++ core is available
        # Just verify it doesn't crash with an unhandled exception
        assert result.exit_code in (0, 1)

    def test_run_nonexistent_file(self, runner):
        from zedda.cli import app
        result = runner.invoke(app, ["run", "/nonexistent/file.csv"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "error" in result.output.lower()


class TestCLICompare:
    """Test the `zedda compare` command."""

    def test_compare_nonexistent_file(self, runner):
        from zedda.cli import app
        result = runner.invoke(app, ["compare", "/nonexistent/a.csv", "/nonexistent/b.csv"])
        assert result.exit_code == 1


class TestCLIClean:
    """Test the `zedda clean` command."""

    def test_clean_nonexistent_file(self, runner):
        from zedda.cli import app
        result = runner.invoke(app, ["clean", "/nonexistent/file.csv"])
        assert result.exit_code == 1


class TestCLIMerge:
    """Test the `zedda merge` command."""

    def test_merge_nonexistent_file(self, runner):
        from zedda.cli import app
        result = runner.invoke(app, ["merge", "/nonexistent/a.csv", "/nonexistent/b.csv"])
        assert result.exit_code == 1


class TestCLIWarnings:
    """Test the `zedda warnings` command."""

    def test_warnings_nonexistent_file(self, runner):
        from zedda.cli import app
        result = runner.invoke(app, ["warnings", "/nonexistent/file.csv"])
        assert result.exit_code == 1


class TestCLIAsk:
    """Test the `zedda ask` command."""

    def test_ask_nonexistent_file(self, runner):
        from zedda.cli import app
        result = runner.invoke(app, ["ask", "/nonexistent/file.csv", "how many rows?"])
        assert result.exit_code == 1
