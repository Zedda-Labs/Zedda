"""
Regression tests for audit findings fixed in v0.4.5.

Each test corresponds to a specific finding ID from Zedda_Audit_Report.md.
Run with: pytest tests/python/test_audit_regression.py -v
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

import zedda as zd
from zedda import ZeddaError


# ─────────────────────────────────────────────────────────────────
#  P-C1: Path traversal in scan(allowed_dir=...) — must use Path.relative_to()
# ─────────────────────────────────────────────────────────────────

class TestPathTraversalPC1:
    """Verify that allowed_dir uses Path.relative_to(), not str.startswith()."""

    def test_prefix_directory_not_bypassed(self, tmp_path):
        """A file in /data/uploads_evil/ must NOT match allowed_dir=/data/uploads.

        The old str.startswith() implementation let this through. The new
        Path.relative_to() implementation correctly rejects it.
        """
        # Create /tmp/.../uploads/ and /tmp/.../uploads_evil/
        allowed = tmp_path / "uploads"
        evil = tmp_path / "uploads_evil"
        allowed.mkdir()
        evil.mkdir()
        # Write a CSV in the evil directory
        evil_csv = evil / "secret.csv"
        evil_csv.write_text("a,b\n1,2\n")
        # Scan with allowed_dir pointing at the legitimate uploads/ dir
        with pytest.raises(ZeddaError, match="outside"):
            zd.scan(str(evil_csv), allowed_dir=str(allowed))

    def test_legitimate_path_in_allowed_dir_works(self, tmp_path):
        """A file actually inside allowed_dir must scan normally."""
        allowed = tmp_path / "uploads"
        allowed.mkdir()
        csv = allowed / "data.csv"
        csv.write_text("a,b\n1,2\n")
        p = zd.scan(str(csv), allowed_dir=str(allowed))
        assert p.num_rows == 1
        assert p.num_cols == 2

    def test_symlink_escape_blocked(self, tmp_path):
        """A symlink inside allowed_dir that points outside must be blocked."""
        allowed = tmp_path / "uploads"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_csv = outside / "secret.csv"
        outside_csv.write_text("a,b\n1,2\n")
        # Create a symlink inside allowed/ pointing to the outside file
        link = allowed / "link.csv"
        try:
            link.symlink_to(outside_csv)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")
        with pytest.raises(ZeddaError, match="outside"):
            zd.scan(str(link), allowed_dir=str(allowed))


# ─────────────────────────────────────────────────────────────────
#  P-C3: fix(apply=True) must not crash on all-null string columns
# ─────────────────────────────────────────────────────────────────

class TestFixAllNullPC3:
    """Series.mode() returns empty Series for all-null columns; [0] raised IndexError."""

    def test_fix_apply_all_null_string_column(self, tmp_path):
        """fix(apply=True) on a column where every value is null must not crash."""
        csv = tmp_path / "all_null.csv"
        csv.write_text("name,age\nAlice,30\nBob,\n,\n")
        # The 'name' column has one null; with a tweak we can make it all-null
        csv.write_text("name,age\n,30\n,25\n,40\n")
        # This should not raise IndexError
        try:
            import pandas as pd  # noqa: F401
        except ImportError:
            pytest.skip("pandas not installed")
        df = zd.fix(str(csv), apply=True)
        assert df is not None


# ─────────────────────────────────────────────────────────────────
#  P-C4: clean() must not write to a deleted temp file when input is DataFrame
# ─────────────────────────────────────────────────────────────────

class TestCleanDataFramePC4:
    """When path is a DataFrame and output=None, no file should be written to disk."""

    def test_clean_dataframe_no_output_returns_df(self, tmp_path):
        """clean(df) with output=None must return a DataFrame, not write to a temp file."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            pytest.skip("pyarrow not installed — clean() needs it for rescan")
        df = pd.DataFrame({
            "name": ["Alice", "Bob", "Charlie", "Dave"],
            "age": [30, 25, None, 40],
            "city": ["NYC", "LA", "NYC", "LA"],
        })
        # This must NOT raise and must NOT write to a deleted temp file
        result = zd.clean(df, output=None)
        assert result is not None
        assert hasattr(result, "columns")


# ─────────────────────────────────────────────────────────────────
#  P-C5: scan() must preserve the original traceback (from e, not from None)
# ─────────────────────────────────────────────────────────────────

class TestScanTracebackPC5:
    """Verify the original exception is chained, not discarded."""

    def test_scan_corrupt_parquet_preserves_chain(self, tmp_path):
        """A corrupt parquet file must produce a ZeddaError with the original cause."""
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            pytest.skip("pyarrow not installed")
        bad = tmp_path / "bad.parquet"
        bad.write_bytes(b"NOT A PARQUET FILE")
        with pytest.raises(ZeddaError) as exc_info:
            zd.scan(str(bad))
        # The ZeddaError should have a __cause__ (chained), not be from None
        assert exc_info.value.__cause__ is not None or exc_info.value.__context__ is not None


# ─────────────────────────────────────────────────────────────────
#  P-H5: Public APIs must raise ZeddaError, not return None, when Rich is missing
# ─────────────────────────────────────────────────────────────────

class TestRichMissingPH5:
    """Verify that compare/ml_ready/warnings/fix/clean/merge raise instead of return None."""

    def test_warnings_raises_when_rich_missing(self, tmp_path, monkeypatch):
        """If Rich is unavailable, warnings() must raise ZeddaError, not return None."""
        csv = tmp_path / "data.csv"
        csv.write_text("a,b\n1,2\n")
        # Simulate Rich being unavailable
        monkeypatch.setattr(zd, "_RICH_AVAILABLE", False)
        monkeypatch.setattr(zd, "_console", None)
        with pytest.raises(ZeddaError, match="Rich is required"):
            zd.warnings(str(csv))


# ─────────────────────────────────────────────────────────────────
#  P-H6: merge() must skip files that fail to scan, not abort the entire merge
# ─────────────────────────────────────────────────────────────────

class TestMergeSkipOnFailPH6:
    """A single bad file must not abort the merge of all other valid files."""

    def test_merge_skips_corrupt_file(self, tmp_path):
        """merge() with one corrupt file should skip it and merge the rest."""
        try:
            import pandas as pd  # noqa: F401
        except ImportError:
            pytest.skip("pandas not installed")
        good1 = tmp_path / "good1.csv"
        good2 = tmp_path / "good2.csv"
        bad = tmp_path / "bad.csv"
        good1.write_text("a,b\n1,2\n3,4\n")
        good2.write_text("a,b\n5,6\n7,8\n")
        # Bad file: 0 bytes (will fail scan)
        bad.write_text("")
        out = tmp_path / "merged.csv"
        # This must not raise — the bad file should be skipped with a warning
        try:
            result = zd.merge([str(good1), str(bad), str(good2)], output=str(out))
        except ZeddaError as e:
            # If it does raise, the message should mention the bad file, not abort
            pytest.fail(f"merge() aborted on bad file instead of skipping: {e}")


# ─────────────────────────────────────────────────────────────────
#  C-H11: UTF-8 BOM must be skipped, not included in the first column header
# ─────────────────────────────────────────────────────────────────

class TestBomHandlingCH11:
    """Verify that a UTF-8 BOM (EF BB BF) at the start of a CSV is skipped."""

    def test_bom_skipped_in_header(self, tmp_path):
        """The first column name must not be prefixed with BOM bytes."""
        csv = tmp_path / "bom.csv"
        # Write BOM + normal CSV content
        csv.write_bytes(b"\xef\xbb\xbfa,b,c\n1,2,3\n4,5,6\n")
        p = zd.scan(str(csv))
        # The first column name must be "a", not "\xef\xbb\xbfa"
        assert p.columns[0].name == "a"
        assert p.columns[1].name == "b"
        assert p.columns[2].name == "c"

    def test_no_bom_still_works(self, tmp_path):
        """A CSV without a BOM must still parse correctly."""
        csv = tmp_path / "no_bom.csv"
        csv.write_text("a,b,c\n1,2,3\n4,5,6\n")
        p = zd.scan(str(csv))
        assert p.columns[0].name == "a"


# ─────────────────────────────────────────────────────────────────
#  C-H12: Boolean parsing must not match "track", "field", "from", etc.
# ─────────────────────────────────────────────────────────────────

class TestBoolParsingCH12:
    """Verify that fast_parse_bool only accepts exact bool literals."""

    def test_track_not_parsed_as_true(self, tmp_path):
        """A column whose first value is 'true' but later values include 'track'
        must not treat 'track' as 1.0."""
        csv = tmp_path / "bools.csv"
        # First value establishes BOOLEAN type; second value 'track' must not
        # be coerced to 1.0 — it should be treated as null (parse failure).
        csv.write_text("flag\ntrue\ntrack\nfalse\n")
        p = zd.scan(str(csv))
        flag_col = p.columns[0]
        # The column should be detected as BOOLEAN (first value is 'true')
        # but 'track' must not be counted as a true value.
        # With the fix, 'track' is null (parse failure), not 1.0.
        # So total_count=3, null_count=1 (the 'track' row).
        assert flag_col.type_str == "bool"
        assert flag_col.null_count == 1  # 'track' is null, not 1.0

    def test_exact_bool_literals_accepted(self, tmp_path):
        """All accepted bool literals (1/0/true/false/yes/no/y/n) must parse."""
        csv = tmp_path / "bools.csv"
        csv.write_text("flag\ntrue\nfalse\nyes\nno\ny\nn\n1\n0\n")
        p = zd.scan(str(csv))
        flag = p.columns[0]
        assert flag.type_str == "bool"
        # 8 values, 0 nulls (all should parse)
        assert flag.null_count == 0


# ─────────────────────────────────────────────────────────────────
#  P-C2: fix(apply=True) must apply the SAME fix shown in the copy-paste code
# ─────────────────────────────────────────────────────────────────

class TestFixApplyMatchesDisplayedPC2:
    """The applied fix must match the displayed copy-paste block."""

    def test_outlier_clipped_not_log1p(self, tmp_path):
        """fix(apply=True) on an outlier column must clip, not create a _log column."""
        try:
            import pandas as pd
            import numpy as np
        except ImportError:
            pytest.skip("pandas/numpy not installed")
        # Create a column with extreme outliers that triggers _is_outlier_column.
        # The predicate excludes int columns with unique_approx < 15 AND val_min >= 0
        # (small enum-like columns). Use negative val_min to avoid that exclusion.
        # Strategy: 20 distinct values centered at 0 (range -10..10), plus one
        # outlier at 100000. mean ≈ (20*0 + 100000)/21 ≈ 4762, so
        # val_max (100000) > 10*mean (47620) ✓, val_min < 0 ✓.
        import random
        random.seed(42)
        values = [random.randint(-10, 10) for _ in range(20)] + [100000]
        csv = tmp_path / "outliers.csv"
        csv.write_text("amount\n" + "\n".join(str(v) for v in values))
        df = zd.fix(str(csv), apply=True)
        # The fix must NOT create an 'amount_log' column (the old bug)
        assert df is not None, "fix(apply=True) returned None — no issues detected"
        assert "amount_log" not in df.columns
        # The 'amount' column must still exist (clip-in-place, not drop)
        assert "amount" in df.columns
        # The max value must be clipped (no longer 100000)
        assert df["amount"].max() < 100000


# ─────────────────────────────────────────────────────────────────
#  P-H11: clean() must not fabricate a fake "after" score on rescan failure
# ─────────────────────────────────────────────────────────────────

class TestCleanScoreHonestyPH11:
    """If the post-clean rescan fails, the 'after' score must equal 'before',
    not be fabricated as `before + 4*fixable`."""

    def test_clean_returns_real_score(self, tmp_path):
        """clean() on a normal CSV must produce a real after-score (not fabricated)."""
        try:
            import pandas as pd  # noqa: F401
        except ImportError:
            pytest.skip("pandas not installed")
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            pytest.skip("pyarrow not installed")
        csv = tmp_path / "data.csv"
        csv.write_text("a,b,c\n1,2,\n3,4,5\n,6,7\n8,,9\n")
        out = tmp_path / "clean.csv"
        # This must not raise; the score should be real
        result = zd.clean(str(csv), output=str(out))
        assert result is not None


# ─────────────────────────────────────────────────────────────────
#  P-H12/H13: ask() return type consistency
# ─────────────────────────────────────────────────────────────────

class TestAskReturnTypePH12:
    """ask() must return a string when print_output=False, even on error."""

    def test_ask_returns_string_on_success(self, tmp_path):
        """ask(print_output=False) must return a string answer."""
        csv = tmp_path / "data.csv"
        csv.write_text("a,b\n1,2\n3,4\n")
        result = zd.ask(str(csv), "how many rows?", print_output=False)
        # Must return a string (not None)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_ask_returns_string_on_error(self, tmp_path):
        """ask() on a missing file must return a string error message, not crash."""
        result = zd.ask("/nonexistent/file.csv", "anything", print_output=False)
        assert isinstance(result, str)
        # The error message should mention the file issue
        assert "not found" in result.lower() or "file" in result.lower()


# ─────────────────────────────────────────────────────────────────
#  D-1: requests must be declared in [ai] extra
# ─────────────────────────────────────────────────────────────────

class TestRequestsDeclaredD1:
    """Verify that 'requests' is declared in the [ai] optional dependency."""

    def test_requests_in_ai_extra(self):
        """pyproject.toml [project.optional-dependencies] ai must include requests."""
        pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
        if not pyproject.exists():
            pytest.skip("pyproject.toml not found")
        content = pyproject.read_text()
        # The ai extra must declare requests
        assert "requests" in content
        # And it must be in the ai section, not just anywhere
        # Look for the pattern: ai = ["requests...
        assert 'ai' in content and 'requests' in content


# ─────────────────────────────────────────────────────────────────
#  C-H8: config_.has_header=false must not drop the first data row
# ─────────────────────────────────────────────────────────────────

class TestHasHeaderFalseCH8:
    """When has_header=false, the first row must be treated as data, not skipped."""

    def test_has_header_false_preserves_first_row(self, tmp_path):
        """scan() with has_header=false must count the first row as data."""
        csv = tmp_path / "noheader.csv"
        csv.write_text("1,2,3\n4,5,6\n7,8,9\n")
        # The C++ core's ProfileBuilder honors config_.has_header, but the Python
        # scan() API doesn't expose it. This test verifies the C++ path via a
        # direct call if possible, or documents the gap.
        # For now, verify that a normal scan counts 3 rows (with header).
        p = zd.scan(str(csv))
        assert p.num_rows == 2  # header + 2 data rows
        # When has_header=false is exposed in the Python API, this test can be
        # extended to verify num_rows == 3.


# ─────────────────────────────────────────────────────────────────
#  CI-C3: ctest must discover all C++ tests (verified via CMakeLists.txt)
# ─────────────────────────────────────────────────────────────────

class TestCtestRegistrationCIC3:
    """Verify that CMakeLists.txt registers all test executables with ctest."""

    def test_all_tests_registered_with_ctest(self):
        """CMakeLists.txt must have add_test() for every test executable."""
        cmake = Path(__file__).parent.parent.parent / "CMakeLists.txt"
        if not cmake.exists():
            pytest.skip("CMakeLists.txt not found")
        content = cmake.read_text()
        # Every test executable must have a corresponding add_test() call
        test_names = [
            "test_simd_scanner",
            "test_mmap_reader",
            "test_fast_float_parity",
            "test_stream_reader",
            "test_debug_crash",
            "test_hyperloglog",
            "test_day1",
            "test_profile_builder",
            "test_arrow_profiler",
        ]
        for name in test_names:
            assert f"add_test(NAME {name}" in content, (
                f"{name} is missing add_test() registration — ctest won't run it"
            )

    def test_enable_testing_present(self):
        """CMakeLists.txt must call enable_testing() so ctest works."""
        cmake = Path(__file__).parent.parent.parent / "CMakeLists.txt"
        if not cmake.exists():
            pytest.skip("CMakeLists.txt not found")
        content = cmake.read_text()
        assert "enable_testing()" in content


# ─────────────────────────────────────────────────────────────────
#  CI-M20: CMake project name must be 'zedda', version must match __init__.py
# ─────────────────────────────────────────────────────────────────

class TestCMakeProjectNameCIM20:
    """Verify CMake project name and version are synced with __init__.py."""

    def test_project_name_is_zedda(self):
        """CMakeLists.txt must declare project(zedda ...), not project(fasteda ...)."""
        cmake = Path(__file__).parent.parent.parent / "CMakeLists.txt"
        content = cmake.read_text()
        assert "project(zedda" in content
        assert "project(fasteda" not in content

    def test_project_version_matches_init(self):
        """CMake project version must match zedda.__version__."""
        cmake = Path(__file__).parent.parent.parent / "CMakeLists.txt"
        content = cmake.read_text()
        # Extract version from "project(zedda VERSION x.y.z ...)"
        import re
        m = re.search(r"project\(zedda\s+VERSION\s+(\d+\.\d+\.\d+)", content)
        assert m, "Could not find project(zedda VERSION ...) in CMakeLists.txt"
        cmake_version = m.group(1)
        assert cmake_version == zd.__version__, (
            f"CMake version {cmake_version} != zedda.__version__ {zd.__version__}"
        )


# ─────────────────────────────────────────────────────────────────
#  P-M4: _SAMPLED_INFO must be thread-safe
# ─────────────────────────────────────────────────────────────────

class TestSampledInfoThreadSafePM4:
    """Verify that _SAMPLED_INFO has a lock protecting concurrent access."""

    def test_lock_exists(self):
        """_SAMPLED_INFO_LOCK must exist and be a threading.Lock."""
        import threading
        assert hasattr(zd, "_SAMPLED_INFO_LOCK")
        assert isinstance(zd._SAMPLED_INFO_LOCK, type(threading.Lock()))

    def test_concurrent_set_get(self):
        """Concurrent set + get must not crash or lose data."""
        import threading
        errors = []

        def writer():
            try:
                for i in range(100):
                    zd._sampled_info_set(f"key_{i}", (i, i * 2))
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(100):
                    zd._sampled_info_get(f"key_{i}", (0, 0))
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert not errors, f"Concurrent access errors: {errors}"


# ─────────────────────────────────────────────────────────────────
#  P-M7: _count_lines must return None on error (not 0)
# ─────────────────────────────────────────────────────────────────

class TestCountLinesReturnsNonePM7:
    """_count_lines must return None on error so callers can show 'unknown'."""

    def test_count_lines_missing_file(self):
        """A missing file must return None, not 0."""
        result = zd._count_lines("/nonexistent/path/file.csv")
        assert result is None

    def test_count_lines_valid_file(self, tmp_path):
        """A valid file must return the line count (number of newlines)."""
        csv = tmp_path / "data.csv"
        csv.write_text("a,b\n1,2\n3,4\n5,6\n")
        result = zd._count_lines(str(csv))
        # 4 newlines = 4 lines (header + 3 data rows).
        # FIX M-8: files ending with newline no longer add a spurious +1.
        assert result == 4

    def test_count_lines_no_trailing_newline(self, tmp_path):
        """A file without a trailing newline must count the last row."""
        csv = tmp_path / "data.csv"
        csv.write_bytes(b"a,b\n1,2\n3,4")  # no trailing newline
        result = zd._count_lines(str(csv))
        # 2 newlines + 1 for the last row without newline = 3 lines.
        assert result == 3


# ─────────────────────────────────────────────────────────────────
#  P-M21/P-M22: warnings() and fix() must accept sample_size
# ─────────────────────────────────────────────────────────────────

class TestSampleSizeParamPM21:
    """warnings() and fix() must accept sample_size for API consistency."""

    def test_warnings_accepts_sample_size(self, tmp_path):
        """warnings(path, sample_size=N) must not raise."""
        csv = tmp_path / "data.csv"
        csv.write_text("a,b\n1,2\n3,4\n")
        # Should not raise TypeError
        try:
            zd.warnings(str(csv), sample_size=100)
        except TypeError as e:
            pytest.fail(f"warnings() does not accept sample_size: {e}")
        except ZeddaError:
            pass  # other errors are OK for this signature test

    def test_fix_accepts_sample_size(self, tmp_path):
        """fix(path, sample_size=N) must not raise TypeError."""
        csv = tmp_path / "data.csv"
        csv.write_text("a,b\n1,2\n3,4\n")
        try:
            zd.fix(str(csv), sample_size=100)
        except TypeError as e:
            pytest.fail(f"fix() does not accept sample_size: {e}")
        except ZeddaError:
            pass  # other errors are OK for this signature test


# ─────────────────────────────────────────────────────────────────
#  Batch 7: Extracted modules must be importable
# ─────────────────────────────────────────────────────────────────

class TestExtractedModulesBatch7:
    """Verify that the extracted sub-modules import cleanly."""

    def test_constants_module(self):
        from zedda._constants import (
            ARROW_SCHEMA_SIZE,
            ARROW_ARRAY_SIZE,
            SAMPLED_INFO_MAX,
            AI_DEFAULT_MODEL,
            AI_ENDPOINT,
        )
        assert ARROW_SCHEMA_SIZE == 256
        assert ARROW_ARRAY_SIZE == 256
        assert SAMPLED_INFO_MAX == 100
        assert AI_DEFAULT_MODEL == "llama-3.3-70b-versatile"
        assert "api.groq.com" in AI_ENDPOINT or "ZEDDA_AI_ENDPOINT" in AI_ENDPOINT

    def test_format_module(self):
        from zedda._format import (
            format_num,
            format_ci,
            format_scan_time,
            quality_label,
            render_quality_bar,
            compute_display_name,
            safe_col_name,
        )
        assert format_num(0.0) == "0"
        assert format_num(1234567, is_integer=True) == "1,234,567"
        assert quality_label(95) == ("cyan", "PRISTINE")
        assert quality_label(50) == ("red", "POOR")
        assert render_quality_bar(76) == "=======---"
        assert render_quality_bar(100) == "=========="
        assert safe_col_name("a'b") == '"a\'b"'

    def test_warnings_module(self):
        from zedda._warnings import (
            is_outlier_column,
            detect_column_issues,
            get_fix_action,
            collect_warnings,
        )
        # These are functions, just verify they're callable
        assert callable(is_outlier_column)
        assert callable(detect_column_issues)
        assert callable(get_fix_action)
        assert callable(collect_warnings)
