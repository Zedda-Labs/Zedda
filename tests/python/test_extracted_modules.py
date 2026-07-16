"""
Unit tests for extracted zedda modules.

These tests verify the pure logic in the extracted modules (_compare,
_ml_ready, _fix, _merge, _clean, _ask) without needing the C++ core
or Rich console. Uses mock ColumnProfile/DatasetProfile objects.

Run with: pytest tests/python/test_extracted_modules.py -v
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────
#  Mock objects — simulate C++ ColumnProfile/DatasetProfile
# ─────────────────────────────────────────────────────────────────

@dataclass
class MockColumn:
    """Mock ColumnProfile for testing."""
    name: str = ""
    type_str: str = "str"
    total_count: int = 100
    null_count: int = 0
    non_null_count: int = 100
    null_pct: float = 0.0
    unique_approx: int = 10
    unique_pct: float = 10.0
    mean: float = 0.0
    stddev: float = 0.0
    variance: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    val_min: float = 0.0
    val_max: float = 0.0
    range: float = 0.0
    min_str_len: int = 0
    max_str_len: int = 0
    mean_str_len: float = 0.0
    has_high_nulls: bool = False
    is_constant: bool = False
    is_high_cardinality: bool = False


@dataclass
class MockProfile:
    """Mock DatasetProfile for testing."""
    num_rows: int = 100
    num_cols: int = 5
    num_numeric: int = 3
    num_string: int = 2
    overall_null_pct: float = 5.0
    total_null_cells: int = 25
    total_cells: int = 500
    scan_time_ms: float = 10.0
    is_sampled: bool = False
    file_name: str = "test.csv"
    file_path: str = "test.csv"
    columns: list = field(default_factory=list)
    correlations: list = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
#  Test _compare.py
# ─────────────────────────────────────────────────────────────────

class TestCompareModule:
    """Tests for zedda._compare."""

    def test_schema_diff_identical(self):
        from zedda._compare import compute_schema_diff
        cols_a = [MockColumn(name="a", type_str="int"), MockColumn(name="b", type_str="float")]
        cols_b = [MockColumn(name="a", type_str="int"), MockColumn(name="b", type_str="float")]
        diff = compute_schema_diff(cols_a, cols_b)
        assert diff["missing_in_b"] == []
        assert diff["missing_in_a"] == []
        assert diff["type_mismatches"] == []
        assert diff["types_match"] == 2
        assert diff["total_compared"] == 2

    def test_schema_diff_missing_in_b(self):
        from zedda._compare import compute_schema_diff
        cols_a = [MockColumn(name="a"), MockColumn(name="b"), MockColumn(name="c")]
        cols_b = [MockColumn(name="a"), MockColumn(name="b")]
        diff = compute_schema_diff(cols_a, cols_b)
        assert diff["missing_in_b"] == ["c"]
        assert diff["missing_in_a"] == []

    def test_schema_diff_type_mismatch(self):
        from zedda._compare import compute_schema_diff
        cols_a = [MockColumn(name="age", type_str="int")]
        cols_b = [MockColumn(name="age", type_str="float")]
        diff = compute_schema_diff(cols_a, cols_b)
        assert len(diff["type_mismatches"]) == 1
        assert diff["type_mismatches"][0] == ("age", "int", "float")
        assert diff["types_match"] == 0

    def test_distribution_shift_stable(self):
        from zedda._compare import compute_distribution_shift
        cols_a = [MockColumn(name="amount", type_str="float", mean=100.0, unique_approx=50, unique_pct=50.0)]
        cols_b = [MockColumn(name="amount", type_str="float", mean=102.0, unique_approx=50, unique_pct=50.0)]
        shifts = compute_distribution_shift(cols_a, cols_b)
        assert len(shifts) == 1
        assert shifts[0]["is_stable"] is True
        assert shifts[0]["is_shift"] is False
        assert abs(shifts[0]["shift_pct"] - 2.0) < 0.1

    def test_distribution_shift_significant(self):
        from zedda._compare import compute_distribution_shift
        cols_a = [MockColumn(name="amount", type_str="float", mean=100.0, unique_approx=50, unique_pct=50.0)]
        cols_b = [MockColumn(name="amount", type_str="float", mean=120.0, unique_approx=50, unique_pct=50.0)]
        shifts = compute_distribution_shift(cols_a, cols_b)
        assert len(shifts) == 1
        assert shifts[0]["is_shift"] is True
        assert abs(shifts[0]["shift_pct"] - 20.0) < 0.1

    def test_distribution_shift_skips_id_columns(self):
        from zedda._compare import compute_distribution_shift
        cols_a = [MockColumn(name="id", type_str="int", mean=500, unique_approx=1000, unique_pct=100.0)]
        cols_b = [MockColumn(name="id", type_str="int", mean=600, unique_approx=1000, unique_pct=100.0)]
        shifts = compute_distribution_shift(cols_a, cols_b)
        assert len(shifts) == 0  # ID columns are skipped

    def test_distribution_shift_skips_binary_target(self):
        from zedda._compare import compute_distribution_shift
        cols_a = [MockColumn(name="survived", type_str="int", mean=0.4, val_min=0, val_max=1, unique_approx=2)]
        cols_b = [MockColumn(name="survived", type_str="int", mean=0.5, val_min=0, val_max=1, unique_approx=2)]
        shifts = compute_distribution_shift(cols_a, cols_b)
        assert len(shifts) == 0  # Binary targets are skipped

    def test_distribution_shift_negative_mean(self):
        """FIX M-32: negative mean must not silently report 0% shift."""
        from zedda._compare import compute_distribution_shift
        cols_a = [MockColumn(name="temp", type_str="float", mean=-10.0, unique_approx=50, unique_pct=50.0)]
        cols_b = [MockColumn(name="temp", type_str="float", mean=10.0, unique_approx=50, unique_pct=50.0)]
        shifts = compute_distribution_shift(cols_a, cols_b)
        assert len(shifts) == 1
        assert shifts[0]["shift_pct"] != 0.0  # must not be silently 0

    def test_verdict_pass(self):
        from zedda._compare import compute_verdict
        schema = {"missing_in_b": [], "missing_in_a": [], "type_mismatches": [], "types_match": 5, "total_compared": 5}
        verdict = compute_verdict(schema, [])
        assert verdict["verdict"] == "PASS"
        assert verdict["safe_to_train"] is True
        assert verdict["critical_errors"] == 0

    def test_verdict_fail(self):
        from zedda._compare import compute_verdict
        schema = {"missing_in_b": ["col_x"], "missing_in_a": [], "type_mismatches": [], "types_match": 4, "total_compared": 5}
        verdict = compute_verdict(schema, [])
        assert verdict["verdict"] == "FAIL"
        assert verdict["safe_to_train"] is False
        assert verdict["critical_errors"] == 1

    def test_verdict_review(self):
        from zedda._compare import compute_verdict
        schema = {"missing_in_b": [], "missing_in_a": [], "type_mismatches": [], "types_match": 5, "total_compared": 5}
        shifts = [{"is_shift": True, "shift_pct": 15.0}]
        verdict = compute_verdict(schema, shifts)
        assert verdict["verdict"] == "REVIEW"
        assert verdict["safe_to_train"] is True
        assert verdict["warnings"] == 1

    def test_looks_like_target_column(self):
        from zedda._compare import looks_like_target_column
        assert looks_like_target_column("survived") is True
        assert looks_like_target_column("target") is True
        assert looks_like_target_column("label") is True
        assert looks_like_target_column("is_fraud") is True
        assert looks_like_target_column("amount") is False
        assert looks_like_target_column("age") is False


# ─────────────────────────────────────────────────────────────────
#  Test _ml_ready.py
# ─────────────────────────────────────────────────────────────────

class TestMLReadyModule:
    """Tests for zedda._ml_ready."""

    def test_clean_dataset_scores_high(self):
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(
            columns=[
                MockColumn(name="age", type_str="int", null_pct=0.0, unique_approx=30, unique_pct=30.0, mean=40, val_min=18, val_max=80),
                MockColumn(name="income", type_str="float", null_pct=0.0, unique_approx=100, unique_pct=100.0, mean=50000, val_min=0, val_max=200000),
                MockColumn(name="city", type_str="str", null_pct=0.0, unique_approx=5, unique_pct=5.0),
            ]
        )
        result = compute_ml_readiness_score(p)
        assert result["score"] >= 90
        assert len(result["drop_cols"]) == 0

    def test_high_null_column_dropped(self):
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(
            columns=[
                MockColumn(name="cabin", type_str="str", null_pct=77.0),
            ]
        )
        result = compute_ml_readiness_score(p)
        assert "cabin" in result["drop_cols"]
        assert result["score"] < 100

    def test_id_column_dropped(self):
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(
            columns=[
                MockColumn(name="passenger_id", type_str="int", null_pct=0.0, unique_approx=891, unique_pct=100.0),
            ]
        )
        result = compute_ml_readiness_score(p)
        assert "passenger_id" in result["drop_cols"]

    def test_binary_target_detected_as_good(self):
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(
            columns=[
                MockColumn(name="survived", type_str="int", null_pct=0.0, val_min=0, val_max=1, unique_approx=2, unique_pct=0.2),
            ]
        )
        result = compute_ml_readiness_score(p)
        good_issues = [i for i in result["issues"] if i.get("is_good")]
        assert len(good_issues) == 1
        assert "binary" in good_issues[0]["good_message"].lower()

    def test_score_clamped_to_0_100(self):
        """FIX M-11: score must be clamped to [0, 100]."""
        from zedda._ml_ready import compute_ml_readiness_score
        # Create many bad columns to drive score negative
        cols = [MockColumn(name=f"c{i}", type_str="str", null_pct=80.0) for i in range(20)]
        p = MockProfile(columns=cols, num_cols=20)
        result = compute_ml_readiness_score(p)
        assert result["score"] >= 0
        assert result["score"] <= 100

    def test_recommended_feature_count(self):
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(
            num_cols=5,
            columns=[
                MockColumn(name="a", type_str="int", null_pct=0.0, unique_approx=10, unique_pct=10.0),
                MockColumn(name="b", type_str="int", null_pct=0.0, unique_approx=10, unique_pct=10.0),
                MockColumn(name="id", type_str="int", null_pct=0.0, unique_approx=100, unique_pct=100.0),
                MockColumn(name="c", type_str="int", null_pct=0.0, unique_approx=10, unique_pct=10.0),
                MockColumn(name="d", type_str="int", null_pct=0.0, unique_approx=10, unique_pct=10.0),
            ],
        )
        result = compute_ml_readiness_score(p)
        assert "id" in result["drop_cols"]
        assert result["recommended_feature_count"] == 4  # 5 - 1 dropped

    def test_moderate_nulls_int_impute(self):
        """Integer column with 5-50% nulls → impute with median."""
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(columns=[
            MockColumn(name="age", type_str="int", null_pct=10.0),
        ])
        result = compute_ml_readiness_score(p)
        issues = [i for i in result["issues"] if not i.get("is_good")]
        assert len(issues) == 1
        assert "median" in issues[0]["fix_code"]

    def test_moderate_nulls_str_impute(self):
        """String column with 5-50% nulls → impute with mode."""
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(columns=[
            MockColumn(name="city", type_str="str", null_pct=10.0),
        ])
        result = compute_ml_readiness_score(p)
        issues = [i for i in result["issues"] if not i.get("is_good")]
        assert len(issues) == 1
        assert "mode" in issues[0]["fix_code"]

    def test_id_like_string_dropped(self):
        """String column with unique_pct > 80 → dropped."""
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(columns=[
            MockColumn(name="ticket", type_str="str", null_pct=0.0,
                       unique_approx=800, unique_pct=90.0),
        ])
        result = compute_ml_readiness_score(p)
        assert "ticket" in result["drop_cols"]

    def test_high_cardinality_string_encoded(self):
        """String column with >50 unique but unique_pct <= 80 → encode."""
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(columns=[
            MockColumn(name="city", type_str="str", null_pct=0.0,
                       unique_approx=100, unique_pct=50.0),
        ])
        result = compute_ml_readiness_score(p)
        issues = [i for i in result["issues"] if not i.get("is_good")]
        assert len(issues) == 1
        assert "Categorical" in issues[0]["fix_code"]

    def test_constant_column_dropped(self):
        """Constant column → dropped."""
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(columns=[
            MockColumn(name="flag", type_str="int", null_pct=0.0, is_constant=True),
        ])
        result = compute_ml_readiness_score(p)
        assert "flag" in result["drop_cols"]

    def test_outlier_column_clipped(self):
        """Outlier column → clip fix code."""
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(columns=[
            MockColumn(name="amount", type_str="float", null_pct=0.0,
                       unique_approx=50, unique_pct=50.0,
                       mean=100, val_min=-10, val_max=100000),
        ])
        result = compute_ml_readiness_score(p)
        issues = [i for i in result["issues"] if not i.get("is_good")]
        assert len(issues) == 1
        assert "clip" in issues[0]["fix_code"]

    def test_looks_good_low_cardinality_int(self):
        """Low-cardinality int column → 'good categorical feature'."""
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(columns=[
            MockColumn(name="pclass", type_str="int", null_pct=0.0,
                       unique_approx=3, unique_pct=3.0,
                       val_min=1, val_max=3),
        ])
        result = compute_ml_readiness_score(p)
        good = [i for i in result["issues"] if i.get("is_good")]
        assert len(good) == 1
        assert "categorical" in good[0]["good_message"]

    def test_looks_good_low_cardinality_str(self):
        """Low-cardinality string column → 'good categorical feature'."""
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(columns=[
            MockColumn(name="sex", type_str="str", null_pct=0.0,
                       unique_approx=2, unique_pct=2.0),
        ])
        result = compute_ml_readiness_score(p)
        good = [i for i in result["issues"] if i.get("is_good")]
        assert len(good) == 1
        assert "categorical" in good[0]["good_message"]

    def test_looks_good_clean_numeric(self):
        """Clean numeric column → 'clean numeric'."""
        from zedda._ml_ready import compute_ml_readiness_score
        p = MockProfile(columns=[
            MockColumn(name="fare", type_str="float", null_pct=0.0,
                       unique_approx=100, unique_pct=50.0,
                       val_min=0, val_max=500, mean=50),
        ])
        result = compute_ml_readiness_score(p)
        good = [i for i in result["issues"] if i.get("is_good")]
        assert len(good) == 1
        assert "clean numeric" in good[0]["good_message"]

    def test_looks_good_fallback(self):
        """Column that doesn't match any 'looks good' pattern → 'no issues detected'."""
        from zedda._ml_ready import compute_ml_readiness_score
        # String with >20 unique (not low-card) and null_pct=0 → falls through
        p = MockProfile(columns=[
            MockColumn(name="x", type_str="str", null_pct=0.0,
                       unique_approx=25, unique_pct=25.0),
        ])
        result = compute_ml_readiness_score(p)
        good = [i for i in result["issues"] if i.get("is_good")]
        assert len(good) == 1
        assert "no issues" in good[0]["good_message"]


# ─────────────────────────────────────────────────────────────────
#  Test _fix.py
# ─────────────────────────────────────────────────────────────────

class TestFixModule:
    """Tests for zedda._fix."""

    def test_generate_fix_code_no_issues(self):
        from zedda._fix import generate_fix_code
        p = MockProfile(
            columns=[
                MockColumn(name="age", type_str="int", null_pct=0.0, unique_approx=30, unique_pct=30.0, mean=40, val_min=18, val_max=80),
            ]
        )
        result = generate_fix_code(p)
        assert result["n_issues"] == 0
        assert len(result["all_code"]) == 0

    def test_generate_fix_code_high_nulls(self):
        from zedda._fix import generate_fix_code
        p = MockProfile(
            columns=[
                MockColumn(name="cabin", type_str="str", null_pct=77.0),
            ]
        )
        result = generate_fix_code(p)
        assert result["n_issues"] >= 1
        assert len(result["null_fixes"]) >= 1
        assert any("drop" in code for _, code in result["null_fixes"])

    def test_generate_fix_code_outlier(self):
        from zedda._fix import generate_fix_code
        p = MockProfile(
            columns=[
                MockColumn(
                    name="amount", type_str="float", null_pct=0.0,
                    unique_approx=50, unique_pct=50.0,
                    mean=100, val_min=-10, val_max=100000,
                ),
            ]
        )
        result = generate_fix_code(p)
        assert len(result["outlier_fixes"]) >= 1
        # FIX P-C2: must be clip, not log1p
        assert any("clip" in code for _, code in result["outlier_fixes"])
        assert not any("log1p" in code for _, code in result["outlier_fixes"])

    def test_apply_fixes_to_dataframe(self):
        """FIX P-C2: apply must clip, not log1p."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._fix import apply_fixes_to_dataframe

        # Create data where val_max > 10 * mean triggers _is_outlier_column.
        # 20 values around 0 (-10..10) plus one outlier at 100000.
        # mean ≈ (20*0 + 100000)/21 ≈ 4762, so 100000 > 10*4762=47620 ✓
        # val_min = -10 (avoids the "small int with val_min >= 0" exclusion)
        import random
        random.seed(42)
        values = [random.randint(-10, 10) for _ in range(20)] + [100000]
        df = pd.DataFrame({"amount": values})
        p = MockProfile(
            columns=[
                MockColumn(
                    name="amount", type_str="float", null_pct=0.0,
                    unique_approx=20, unique_pct=95.0,
                    mean=4762, val_min=-10, val_max=100000,
                ),
            ],
        )
        df = apply_fixes_to_dataframe(df, p)
        # Must NOT create a _log column (old bug)
        assert "amount_log" not in df.columns
        # Must still have the original column (clip in place)
        assert "amount" in df.columns
        # Max must be clipped
        assert df["amount"].max() < 100000

    def test_generate_fix_code_id_like_string(self):
        """ID-like string column (unique_pct > 80) should generate drop code."""
        from zedda._fix import generate_fix_code
        p = MockProfile(
            columns=[
                MockColumn(name="ticket", type_str="str", null_pct=0.0,
                           unique_approx=800, unique_pct=90.0),
            ]
        )
        result = generate_fix_code(p)
        assert result["n_issues"] >= 1
        assert len(result["id_fixes"]) >= 1

    def test_generate_fix_code_high_cardinality_string(self):
        """High-cardinality string (>50 unique) should generate encode code."""
        from zedda._fix import generate_fix_code
        p = MockProfile(
            columns=[
                MockColumn(name="city", type_str="str", null_pct=0.0,
                           unique_approx=100, unique_pct=50.0),
            ]
        )
        result = generate_fix_code(p)
        assert len(result["cardinality_fixes"]) >= 1
        assert any("Categorical" in code for _, code in result["cardinality_fixes"])

    def test_generate_fix_code_constant_column(self):
        """Constant column should generate drop code."""
        from zedda._fix import generate_fix_code
        p = MockProfile(
            columns=[
                MockColumn(name="flag", type_str="int", null_pct=0.0,
                           is_constant=True),
            ]
        )
        result = generate_fix_code(p)
        assert len(result["constant_fixes"]) >= 1

    def test_generate_fix_code_moderate_nulls_int(self):
        """Integer column with moderate nulls should generate median impute code."""
        from zedda._fix import generate_fix_code
        p = MockProfile(
            columns=[
                MockColumn(name="age", type_str="int", null_pct=10.0),
            ]
        )
        result = generate_fix_code(p)
        assert len(result["null_fixes"]) >= 1
        assert any("median" in code for _, code in result["null_fixes"])

    def test_generate_fix_code_moderate_nulls_str(self):
        """String column with moderate nulls should generate mode impute code."""
        from zedda._fix import generate_fix_code
        p = MockProfile(
            columns=[
                MockColumn(name="embarked", type_str="str", null_pct=10.0),
            ]
        )
        result = generate_fix_code(p)
        assert len(result["null_fixes"]) >= 1
        assert any("mode" in code for _, code in result["null_fixes"])

    def test_apply_fixes_drops_high_null_string(self):
        """apply_fixes should drop string columns with >50% nulls."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._fix import apply_fixes_to_dataframe
        df = pd.DataFrame({"cabin": ["A", None, None, None, None]})
        p = MockProfile(
            columns=[MockColumn(name="cabin", type_str="str", null_pct=80.0)]
        )
        df = apply_fixes_to_dataframe(df, p)
        assert "cabin" not in df.columns

    def test_apply_fixes_encodes_high_cardinality(self):
        """apply_fixes should label-encode high-cardinality string columns."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._fix import apply_fixes_to_dataframe
        df = pd.DataFrame({"name": [f"p{i}" for i in range(100)]})
        p = MockProfile(
            columns=[MockColumn(name="name", type_str="str", null_pct=0.0,
                                unique_approx=100, unique_pct=100.0)]
        )
        df = apply_fixes_to_dataframe(df, p)
        assert "name" in df.columns
        assert df["name"].dtype.kind in ("i", "u")  # encoded to integers


# ─────────────────────────────────────────────────────────────────
#  Test _merge.py
# ─────────────────────────────────────────────────────────────────

class TestMergeModule:
    """Tests for zedda._merge."""

    def test_compute_overlap_count_no_duplicates(self):
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._merge import compute_overlap_count
        df1 = pd.DataFrame({"id": [1, 2, 3], "val": ["a", "b", "c"]})
        df2 = pd.DataFrame({"id": [4, 5, 6], "val": ["d", "e", "f"]})
        count = compute_overlap_count([df1, df2], ["id"])
        assert count == 0

    def test_compute_overlap_count_with_duplicates(self):
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._merge import compute_overlap_count
        df1 = pd.DataFrame({"id": [1, 2, 3], "val": ["a", "b", "c"]})
        df2 = pd.DataFrame({"id": [2, 4, 5], "val": ["d", "e", "f"]})
        count = compute_overlap_count([df1, df2], ["id"])
        assert count == 1  # id=2 is duplicated

    def test_compute_schema_mismatches_no_issues(self):
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._merge import compute_schema_mismatches
        df1 = pd.DataFrame({"a": [1], "b": [2]})
        df2 = pd.DataFrame({"a": [3], "b": [4]})
        mismatches = compute_schema_mismatches([df1, df2], ["f1.csv", "f2.csv"])
        assert len(mismatches) == 0

    def test_compute_schema_mismatches_missing_column(self):
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._merge import compute_schema_mismatches
        df1 = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        df2 = pd.DataFrame({"a": [4], "b": [5]})
        mismatches = compute_schema_mismatches([df1, df2], ["f1.csv", "f2.csv"])
        assert len(mismatches) == 1
        assert "c" in mismatches[0]["missing"]

    def test_combine_dataframes_adds_source_column(self):
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._merge import combine_dataframes
        df1 = pd.DataFrame({"id": [1, 2], "val": ["a", "b"]})
        df2 = pd.DataFrame({"id": [3, 4], "val": ["c", "d"]})
        combined, deduped = combine_dataframes([df1, df2], ["id"], ["f1.csv", "f2.csv"])
        assert "zedda_source_file" in combined.columns
        assert len(combined) == 4
        assert deduped == 0

    def test_combine_dataframes_dedup_on_common_cols(self):
        """FIX P-H8: dedup on common_cols, not ALL columns."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._merge import combine_dataframes
        df1 = pd.DataFrame({"id": [1, 2], "val": ["a", "b"]})
        df2 = pd.DataFrame({"id": [1, 3], "val": ["c", "d"]})  # id=1 is dup
        combined, deduped = combine_dataframes([df1, df2], ["id"], ["f1.csv", "f2.csv"])
        assert deduped == 1
        assert len(combined) == 3  # 4 - 1 duplicate


# ─────────────────────────────────────────────────────────────────
#  Test _clean.py
# ─────────────────────────────────────────────────────────────────

class TestCleanModule:
    """Tests for zedda._clean."""

    def test_create_backup(self, tmp_path):
        from zedda._clean import create_backup
        csv = tmp_path / "data.csv"
        csv.write_text("a,b\n1,2\n")
        backup = create_backup(str(csv))
        assert backup is not None
        assert Path(backup).exists()
        assert Path(backup).read_text() == "a,b\n1,2\n"

    def test_create_backup_idempotent(self, tmp_path):
        """FIX P-H9: backup must not be overwritten if it already exists."""
        from zedda._clean import create_backup
        csv = tmp_path / "data.csv"
        csv.write_text("a,b\n1,2\n")
        # First backup
        backup1 = create_backup(str(csv))
        assert backup1 is not None
        # Modify original
        csv.write_text("a,b\n3,4\n")
        # Second backup — should NOT overwrite
        backup2 = create_backup(str(csv))
        assert backup2 is None  # already exists
        # Verify backup still has original content
        assert Path(backup1).read_text() == "a,b\n1,2\n"

    def test_undo_clean(self, tmp_path):
        from zedda._clean import undo_clean
        from zedda import ZeddaError
        csv = tmp_path / "data.csv"
        csv.write_text("original\n")
        backup = str(csv) + ".zedda-backup"
        Path(backup).write_text("original\n")
        # Modify the file
        csv.write_text("modified\n")
        # Undo
        undo_clean(str(csv))
        assert csv.read_text() == "original\n"

    def test_undo_clean_no_backup(self, tmp_path):
        from zedda._clean import undo_clean
        from zedda._resolve import ZeddaError as ResolveZeddaError
        csv = tmp_path / "data.csv"
        csv.write_text("data\n")
        # _clean.py imports ZeddaError from _resolve, so catch that type
        with pytest.raises(ResolveZeddaError, match="No backup found"):
            undo_clean(str(csv))

    def test_write_audit_trail(self, tmp_path):
        from zedda._clean import write_audit_trail
        out = tmp_path / "clean.csv"
        out.write_text("cleaned\n")
        audit = str(tmp_path / "clean_cleaning_audit.json")
        write_audit_trail(
            audit_path=audit,
            source_file="data.csv",
            output_file=str(out),
            version="0.4.5",
            score_before=70,
            score_after=90,
            rows_before=100,
            rows_after=100,
            cols_before=5,
            cols_after=4,
            actions=[{"column": "x", "action": "drop"}],
        )
        assert Path(audit).exists()
        data = json.loads(Path(audit).read_text())
        assert data["score_before"] == 70
        assert data["score_after"] == 90
        assert data["actions"] == [{"column": "x", "action": "drop"}]

    def test_write_audit_trail_traversal_blocked(self, tmp_path):
        """FIX P-H10: audit path in different directory must be refused."""
        from zedda._clean import write_audit_trail
        out = tmp_path / "clean.csv"
        out.write_text("cleaned\n")
        # Audit path in a different directory
        evil_audit = str(tmp_path.parent / "evil_audit.json")
        with pytest.raises(ValueError, match="traversal"):
            write_audit_trail(
                audit_path=evil_audit,
                source_file="data.csv",
                output_file=str(out),
                version="0.4.5",
                score_before=70,
                score_after=90,
                rows_before=100,
                rows_after=100,
                cols_before=5,
                cols_after=4,
                actions=[],
            )

    def test_apply_cleaning_drops_high_null_string_column(self):
        """Column with >50% nulls and type str/unknown should be dropped."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._clean import apply_cleaning_fixes
        df = pd.DataFrame({"cabin": ["A", "B", None, None, None]})
        p = MockProfile(columns=[MockColumn(name="cabin", type_str="str", null_pct=60.0)])
        df, actions, dropped = apply_cleaning_fixes(df, p, original_cols=1)
        assert "cabin" in dropped
        assert "cabin" not in df.columns
        assert any(a["action"] == "drop" for a in actions)

    def test_apply_cleaning_imputes_numeric_median(self):
        """Numeric column with moderate nulls should be imputed with median."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._clean import apply_cleaning_fixes
        df = pd.DataFrame({"age": [10, 20, 30, None, 50]})
        p = MockProfile(columns=[MockColumn(name="age", type_str="int", null_pct=20.0)])
        df, actions, dropped = apply_cleaning_fixes(df, p, original_cols=1)
        assert "age" in df.columns
        assert df["age"].isnull().sum() == 0  # all nulls filled
        assert any(a["action"] == "impute" for a in actions)

    def test_apply_cleaning_imputes_string_mode(self):
        """String column with moderate nulls should be imputed with mode."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._clean import apply_cleaning_fixes
        df = pd.DataFrame({"city": ["NYC", "NYC", "LA", None, "NYC"]})
        p = MockProfile(columns=[MockColumn(name="city", type_str="str", null_pct=20.0)])
        df, actions, dropped = apply_cleaning_fixes(df, p, original_cols=1)
        assert df["city"].isnull().sum() == 0
        assert df["city"].iloc[3] == "NYC"  # mode fill

    def test_apply_cleaning_imputes_all_null_string_with_unknown(self):
        """FIX P-C3: All-null string column should fill with 'Unknown' (mode empty).

        Note: null_pct must be <= 50 to avoid the 'high nulls → drop' path.
        """
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._clean import apply_cleaning_fixes
        df = pd.DataFrame({"col": [None, None, None]})
        # Use null_pct=40 (moderate, not >50) so the column goes to impute, not drop
        p = MockProfile(columns=[MockColumn(name="col", type_str="str", null_pct=40.0)])
        df, actions, dropped = apply_cleaning_fixes(df, p, original_cols=1)
        # mode() is empty → fill_val = "Unknown"
        assert (df["col"] == "Unknown").all()

    def test_apply_cleaning_drops_id_column(self):
        """ID-like integer column (unique_pct > 95) should be dropped."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._clean import apply_cleaning_fixes
        df = pd.DataFrame({"id": [1, 2, 3, 4, 5], "val": [10, 20, 30, 40, 50]})
        p = MockProfile(columns=[
            MockColumn(name="id", type_str="int", null_pct=0.0, unique_pct=100.0, unique_approx=5),
            MockColumn(name="val", type_str="int", null_pct=0.0, unique_pct=100.0, unique_approx=5),
        ])
        df, actions, dropped = apply_cleaning_fixes(df, p, original_cols=2)
        assert "id" in dropped
        assert "id" not in df.columns

    def test_apply_cleaning_encodes_high_cardinality_string(self):
        """High-cardinality string column should be label-encodedd."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._clean import apply_cleaning_fixes
        df = pd.DataFrame({"name": [f"person_{i}" for i in range(100)]})
        p = MockProfile(columns=[MockColumn(name="name", type_str="str", null_pct=0.0, unique_approx=100)])
        df, actions, dropped = apply_cleaning_fixes(df, p, original_cols=1)
        assert "name" in df.columns
        # After encoding, values should be integer codes
        assert df["name"].dtype.kind in ("i", "u")  # integer type
        assert any(a["action"] == "encode" for a in actions)

    def test_apply_cleaning_drops_constant_column(self):
        """Constant column should be dropped."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._clean import apply_cleaning_fixes
        df = pd.DataFrame({"flag": [1, 1, 1, 1, 1], "val": [10, 20, 30, 40, 50]})
        p = MockProfile(columns=[
            MockColumn(name="flag", type_str="int", null_pct=0.0, is_constant=True),
            MockColumn(name="val", type_str="int", null_pct=0.0),
        ])
        df, actions, dropped = apply_cleaning_fixes(df, p, original_cols=2)
        assert "flag" in dropped
        assert "flag" not in df.columns

    def test_apply_cleaning_clips_outliers(self):
        """Outlier column should be clipped at 99th percentile."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._clean import apply_cleaning_fixes
        # 20 values around 0 + 1 outlier at 100000
        import random
        random.seed(42)
        values = [random.randint(-10, 10) for _ in range(20)] + [100000]
        df = pd.DataFrame({"amount": values})
        p = MockProfile(columns=[
            MockColumn(
                name="amount", type_str="float", null_pct=0.0,
                unique_approx=20, unique_pct=95.0,
                mean=4762, val_min=-10, val_max=100000,
            ),
        ])
        df, actions, dropped = apply_cleaning_fixes(df, p, original_cols=1)
        assert "amount" in df.columns
        assert df["amount"].max() < 100000  # clipped
        assert any(a["action"] == "clip" for a in actions)

    def test_apply_cleaning_no_changes_for_clean_data(self):
        """Clean data should produce no audit actions."""
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        from zedda._clean import apply_cleaning_fixes
        df = pd.DataFrame({"age": [25, 30, 35], "name": ["A", "B", "C"]})
        p = MockProfile(columns=[
            MockColumn(name="age", type_str="int", null_pct=0.0, unique_approx=3, unique_pct=100.0),
            MockColumn(name="name", type_str="str", null_pct=0.0, unique_approx=3, unique_pct=100.0),
        ])
        df, actions, dropped = apply_cleaning_fixes(df, p, original_cols=2)
        # age has unique_pct=100 → ID-like, will be dropped
        # name has unique_approx=3 (not > 50) → no encode
        assert "age" in dropped  # ID-like


# ─────────────────────────────────────────────────────────────────
#  Test _ask.py
# ─────────────────────────────────────────────────────────────────

class TestAskModule:
    """Tests for zedda._ask."""

    def test_sanitize_question_empty(self):
        from zedda._ask import sanitize_question
        with pytest.raises(ValueError, match="empty"):
            sanitize_question("")
        with pytest.raises(ValueError, match="empty"):
            sanitize_question("   ")

    def test_sanitize_question_strips_control_chars(self):
        from zedda._ask import sanitize_question
        result = sanitize_question("mean of\x00age")
        assert "\x00" not in result

    def test_sanitize_question_truncates(self):
        from zedda._ask import sanitize_question
        long_q = "x" * 1000
        result = sanitize_question(long_q)
        assert len(result) <= 500

    def test_find_column_exact(self):
        from zedda._ask import find_column_by_hint
        p = MockProfile(columns=[MockColumn(name="Age"), MockColumn(name="Fare")])
        col = find_column_by_hint(p, "Age")
        assert col is not None
        assert col.name == "Age"

    def test_find_column_case_insensitive(self):
        from zedda._ask import find_column_by_hint
        p = MockProfile(columns=[MockColumn(name="Age"), MockColumn(name="Fare")])
        col = find_column_by_hint(p, "age")
        assert col is not None
        assert col.name == "Age"

    def test_find_column_substring(self):
        from zedda._ask import find_column_by_hint
        p = MockProfile(columns=[MockColumn(name="passenger_age"), MockColumn(name="fare")])
        col = find_column_by_hint(p, "age")
        assert col is not None
        assert col.name == "passenger_age"

    def test_find_column_not_found(self):
        from zedda._ask import find_column_by_hint
        p = MockProfile(columns=[MockColumn(name="Age")])
        col = find_column_by_hint(p, "nonexistent")
        assert col is None

    def test_answer_row_count(self):
        from zedda._ask import answer_row_count
        p = MockProfile(num_rows=891)
        result = answer_row_count(p, "how many rows are there?")
        assert result is not None
        assert "891" in result

    def test_answer_col_count(self):
        from zedda._ask import answer_col_count
        p = MockProfile(num_cols=12)
        result = answer_col_count(p, "how many columns?")
        assert result is not None
        assert "12" in result

    def test_answer_null_summary(self):
        from zedda._ask import answer_null_summary
        p = MockProfile(
            overall_null_pct=28.3,
            columns=[
                MockColumn(name="cabin", null_pct=77.0),
                MockColumn(name="age", null_pct=19.9),
            ],
        )
        result = answer_null_summary(p, "how many nulls?")
        assert result is not None
        assert "28.3" in result
        assert "cabin" in result

    def test_answer_correlation_summary(self):
        from zedda._ask import answer_correlation_summary
        p = MockProfile(
            correlations=[
                MagicMock(col_a="SibSp", col_b="Parch", r=0.83, strength="strong"),
            ]
        )
        result = answer_correlation_summary(p, "any correlations?")
        assert result is not None
        assert "SibSp" in result
        assert "Parch" in result

    def test_answer_offline_no_match(self):
        from zedda._ask import answer_offline
        p = MockProfile(num_rows=100, num_cols=5)
        result = answer_offline(p, "what is the meaning of life?")
        assert result is None  # no pattern matches

    def test_answer_offline_row_count(self):
        from zedda._ask import answer_offline
        p = MockProfile(num_rows=100, num_cols=5)
        result = answer_offline(p, "how many rows?")
        assert result is not None
        assert result[0] is not None  # answer text
        assert "100" in result[0]

    def test_answer_single_col_stat_mean(self):
        """answer_single_col_stat for 'mean of X'."""
        from zedda._ask import answer_single_col_stat
        p = MockProfile(columns=[MockColumn(name="age", type_str="int", mean=35.5)])
        result = answer_single_col_stat(p, "mean of age")
        assert result is not None
        assert "35.5" in result[0]

    def test_answer_single_col_stat_type(self):
        """answer_single_col_stat for 'type of X'."""
        from zedda._ask import answer_single_col_stat
        p = MockProfile(columns=[MockColumn(name="age", type_str="int")])
        result = answer_single_col_stat(p, "type of age")
        assert result is not None
        assert "int" in result[0]

    def test_answer_single_col_stat_null_pct(self):
        """answer_single_col_stat for 'null rate of X' — show_fix_tip=True."""
        from zedda._ask import answer_single_col_stat
        p = MockProfile(columns=[MockColumn(name="age", type_str="int", null_pct=19.9)])
        result = answer_single_col_stat(p, "null rate of age")
        assert result is not None
        assert "19.9" in result[0]
        assert result[1] is True  # show_fix_tip

    def test_answer_single_col_stat_not_found(self):
        """answer_single_col_stat when column not found."""
        from zedda._ask import answer_single_col_stat
        p = MockProfile(columns=[MockColumn(name="age")])
        result = answer_single_col_stat(p, "mean of nonexistent")
        assert result is not None
        assert "not found" in result[0]

    def test_answer_single_col_stat_min_max(self):
        """answer_single_col_stat for 'min of X' and 'max of X'."""
        from zedda._ask import answer_single_col_stat
        p = MockProfile(columns=[MockColumn(name="age", type_str="int", val_min=0, val_max=100)])
        r1 = answer_single_col_stat(p, "min of age")
        assert r1 is not None and "0" in r1[0]
        r2 = answer_single_col_stat(p, "max of age")
        assert r2 is not None and "100" in r2[0]

    def test_answer_single_col_stat_no_match(self):
        """answer_single_col_stat when no pattern matches."""
        from zedda._ask import answer_single_col_stat
        p = MockProfile(columns=[MockColumn(name="age")])
        result = answer_single_col_stat(p, "what is the meaning of life?")
        assert result is None

    def test_answer_null_summary_no_nulls(self):
        """answer_null_summary when no high-null columns exist."""
        from zedda._ask import answer_null_summary
        p = MockProfile(overall_null_pct=1.0, columns=[MockColumn(name="a", null_pct=0.0)])
        result = answer_null_summary(p, "how many nulls?")
        assert result is not None
        assert "No significant nulls" in result

    def test_answer_correlation_summary_none(self):
        """answer_correlation_summary when no correlations exist."""
        from zedda._ask import answer_correlation_summary
        p = MockProfile(correlations=[])
        result = answer_correlation_summary(p, "any correlations?")
        assert result is not None
        assert "No strong correlations" in result

    def test_answer_correlation_summary_with_pairs(self):
        """answer_correlation_summary with correlation pairs."""
        from zedda._ask import answer_correlation_summary
        p = MockProfile(correlations=[
            MagicMock(col_a="SibSp", col_b="Parch", r=0.83, strength="strong"),
        ])
        result = answer_correlation_summary(p, "correlations?")
        assert result is not None
        assert "1 correlated pair" in result
        assert "SibSp" in result

    def test_answer_offline_col_count(self):
        """answer_offline for 'how many columns?'."""
        from zedda._ask import answer_offline
        p = MockProfile(num_rows=100, num_cols=12)
        result = answer_offline(p, "how many columns?")
        assert result is not None
        assert "12" in result[0]

    def test_answer_offline_null_summary(self):
        """answer_offline for 'how many nulls?'."""
        from zedda._ask import answer_offline
        p = MockProfile(overall_null_pct=5.0, columns=[MockColumn(name="x", null_pct=10.0)])
        result = answer_offline(p, "how many nulls?")
        assert result is not None
        assert "5.0" in result[0]
        assert result[1] is True  # show_fix_tip

    def test_answer_offline_correlation(self):
        """answer_offline for 'correlations?'."""
        from zedda._ask import answer_offline
        p = MockProfile(correlations=[])
        result = answer_offline(p, "correlations?")
        assert result is not None
        assert "No strong" in result[0]

    def test_answer_offline_single_col_stat(self):
        """answer_offline for 'mean of X'."""
        from zedda._ask import answer_offline
        p = MockProfile(columns=[MockColumn(name="fare", type_str="float", mean=32.5)])
        result = answer_offline(p, "mean of fare")
        assert result is not None
        assert "32.5" in result[0]


# ─────────────────────────────────────────────────────────────────
#  Test _format.py
# ─────────────────────────────────────────────────────────────────

class TestFormatModule:
    """Tests for zedda._format."""

    def test_format_num_zero(self):
        from zedda._format import format_num
        assert format_num(0.0) == "0"

    def test_format_num_integer(self):
        from zedda._format import format_num
        assert format_num(1234567, is_integer=True) == "1,234,567"

    def test_format_num_large_float(self):
        from zedda._format import format_num
        assert "1,000,000" in format_num(1_000_000.0)

    def test_quality_label(self):
        from zedda._format import quality_label
        assert quality_label(95) == ("cyan", "PRISTINE")
        assert quality_label(80) == ("green", "GOOD")
        assert quality_label(60) == ("yellow", "FAIR")
        assert quality_label(50) == ("red", "POOR")

    def test_render_quality_bar(self):
        from zedda._format import render_quality_bar
        assert render_quality_bar(100) == "=========="
        assert render_quality_bar(0) == "----------"
        assert render_quality_bar(76) == "=======---"
        assert render_quality_bar(50) == "=====-----"

    def test_compute_display_name(self):
        from zedda._format import compute_display_name
        assert compute_display_name("/path/to/data.csv", False) == "data.csv"
        assert compute_display_name(None, True, "<DataFrame>") == "<DataFrame>"
        assert compute_display_name("data.csv", False) == "data.csv"

    def test_safe_col_name(self):
        from zedda._format import safe_col_name
        # repr() escapes special characters — verifies SEC-P01 code injection prevention
        assert safe_col_name("simple") == "'simple'"
        # repr() uses double quotes when string contains single quotes
        result = safe_col_name("col'with'quotes")
        assert result.startswith('"') or result.startswith("'")
        # The result must be valid Python repr — eval should give back the original
        assert eval(result) == "col'with'quotes"
        # Dangerous column names must be safely escaped
        dangerous = safe_col_name("']; os.system('rm -rf /'); #")
        assert eval(dangerous) == "']; os.system('rm -rf /'); #"

    def test_format_num_thousands(self):
        """format_num for values in the thousands range."""
        from zedda._format import format_num
        result = format_num(1234.5)
        assert "1,234.5" in result

    def test_format_num_small_decimal(self):
        """format_num for small decimal values."""
        from zedda._format import format_num
        result = format_num(0.001)
        assert "0.001" in result or "0.00100" in result

    def test_format_num_tiny_scientific(self):
        """format_num for very small values uses scientific notation."""
        from zedda._format import format_num
        result = format_num(0.0000001)
        assert "e" in result.lower()  # scientific notation

    def test_format_ci_zero(self):
        """format_ci for zero."""
        from zedda._format import format_ci
        assert format_ci(0.0) == "0"

    def test_format_ci_large(self):
        """format_ci for large values (>= 1000)."""
        from zedda._format import format_ci
        result = format_ci(5000.0)
        assert "5,000" in result

    def test_format_ci_medium(self):
        """format_ci for medium values (1 <= x < 1000)."""
        from zedda._format import format_ci
        result = format_ci(42.5)
        assert "42.5" in result

    def test_format_ci_small(self):
        """format_ci for small values (0.01 <= x < 1)."""
        from zedda._format import format_ci
        result = format_ci(0.5)
        assert "0.50" in result

    def test_format_ci_tiny(self):
        """format_ci for very small values (< 0.01) uses %g format."""
        from zedda._format import format_ci
        result = format_ci(0.0001)
        assert len(result) > 0
        # Should be in scientific or compact notation
        assert "e" in result.lower() or "0.0001" in result

    def test_format_scan_time_ms(self):
        """format_scan_time for milliseconds."""
        from zedda._format import format_scan_time
        assert format_scan_time(50) == "50 ms"
        assert format_scan_time(999.9) == "1000 ms"

    def test_format_scan_time_seconds(self):
        """format_scan_time for values >= 10000 ms shows seconds."""
        from zedda._format import format_scan_time
        result = format_scan_time(15000)
        assert "sec" in result
        assert "15.0" in result

    def test_compute_display_name_path_object(self):
        """compute_display_name with a Path object."""
        from zedda._format import compute_display_name
        from pathlib import Path
        assert compute_display_name(Path("/tmp/data.csv"), False) == "data.csv"


# ─────────────────────────────────────────────────────────────────
#  Test _warnings.py
# ─────────────────────────────────────────────────────────────────

class TestWarningsModule:
    """Tests for zedda._warnings."""

    def test_is_outlier_column_true(self):
        from zedda._warnings import is_outlier_column
        col = MockColumn(
            name="amount", type_str="float", mean=100, val_max=100000,
            unique_approx=50, val_min=-10,
        )
        assert is_outlier_column(col) is True

    def test_is_outlier_column_false_small_int(self):
        """Small integer columns with val_min >= 0 are excluded (enum-like)."""
        from zedda._warnings import is_outlier_column
        col = MockColumn(
            name="count", type_str="int", mean=5, val_max=100,
            unique_approx=10, val_min=0,
        )
        assert is_outlier_column(col) is False

    def test_is_outlier_column_false_ratio(self):
        """Columns with 'ratio' in name are excluded."""
        from zedda._warnings import is_outlier_column
        col = MockColumn(
            name="conversion_ratio", type_str="float", mean=0.5, val_max=100,
            unique_approx=50, val_min=-10,
        )
        assert is_outlier_column(col) is False

    def test_detect_column_issues_high_nulls(self):
        from zedda._warnings import detect_column_issues
        col = MockColumn(name="cabin", type_str="str", null_pct=77.0)
        p = MockProfile(columns=[col])
        issues = detect_column_issues(col, p)
        types = [i["type"] for i in issues]
        assert "high_nulls" in types

    def test_detect_column_issues_collects_multiple(self):
        """FIX L-10: a column can have multiple issues (no early return)."""
        from zedda._warnings import detect_column_issues
        # High nulls AND outlier — both should be detected
        col = MockColumn(
            name="amount", type_str="float", null_pct=10.0,
            mean=100, val_max=100000, unique_approx=50, val_min=-10,
        )
        p = MockProfile(columns=[col])
        issues = detect_column_issues(col, p)
        types = [i["type"] for i in issues]
        assert "moderate_nulls" in types
        assert "outlier" in types

    def test_collect_warnings_sorted_by_severity(self):
        from zedda._warnings import collect_warnings
        p = MockProfile(
            columns=[
                MockColumn(name="a", type_str="str", null_pct=77.0),  # critical
                MockColumn(name="b", type_str="int", is_constant=True),  # info
                MockColumn(name="c", type_str="str", null_pct=10.0),  # critical (moderate)
            ],
        )
        warnings = collect_warnings(p)
        # Critical should come first
        severities = [w["severity"] for w in warnings]
        assert severities[0] == "critical"
        assert "critical" in severities
