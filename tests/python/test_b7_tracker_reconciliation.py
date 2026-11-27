"""
test_b7_tracker_reconciliation.py

B7 Tracker Reconciliation Regression Tests
==========================================
These tests encode the live code state verified in session 2026-10-06
(branch: remediation/b7-tracker-reconciliation) for findings F-001,
F-003, F-014, F-024, F-025, F-038, and F-040.

Key constraints discovered live (not from prior audit docs):
- DISTINCT_VALUES_CAP = 100,000 (column_accumulator.hpp:108) -- 200
  distinct string rows are well within exact tracking.  To force
  approximate (HLL) path for is_unique, either (a) exceed 100k rows,
  or (b) use a sampled scan.  The prior audit's claim that "approximate
  uniqueness can PASS" was stale: _compat.py lines 115-124 explicitly
  use MetricStatus.APPROXIMATE when exact_unique_valid is False.
- RuleResult.__post_init__ (models.py:347-352) enforces that
  evaluated=False forces status=INDETERMINATE at construction time,
  making the F-038 invariant structurally guaranteed.
"""

from __future__ import annotations
import ast
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_BUILDER = REPO_ROOT / "src" / "core" / "profile_builder.cpp"
BINDINGS = REPO_ROOT / "src" / "bindings" / "bindings.cpp"
COLUMN_ACC = REPO_ROOT / "include" / "zedda" / "column_accumulator.hpp"
COMPARE_PY = REPO_ROOT / "python" / "zedda" / "_compare.py"
VALIDATE_PY = REPO_ROOT / "python" / "zedda" / "_validate.py"
COMPAT_PY = REPO_ROOT / "python" / "zedda" / "_compat.py"
MODELS_PY = REPO_ROOT / "python" / "zedda" / "_models.py"
SCAN_PY = REPO_ROOT / "python" / "zedda" / "_scan.py"


# ─────────────────────────────────────────────────────────────────
# F-001 / F-003: Quote-aware CSV chunking
# Audit claim: parallel CSV used physical-newline boundaries,
# silently corrupting quoted multiline records at chunk boundaries.
#
# Current state (verified 2026-10-06, profile_builder.cpp lines
# 694-755):
#   - Pre-scan loop tracks quote state across the entire file BEFORE
#     assigning chunk boundaries.
#   - When embedded newlines detected, has_embedded_newlines=true and
#     num_threads is forced to 1 (line 744-745).
#   - safe_boundaries array implements quote-aware chunk splitting for
#     files without embedded newlines.
# STATUS: PARTIALLY RESOLVED.  Embedded-newline files fall back to
# single-thread (correct).  Multi-thread path with safe_boundaries is
# quote-aware at boundary selection.  Full "Pass1: boundary scan +
# Pass 2: parallel parse" as specified in architecture.md §3 is
# structurally present.  Remaining work: fuzz testing of boundary edge
# cases (still on the P0 list but severity is lower -- no silent
# corruption, only safe fallback).
# ─────────────────────────────────────────────────────────────────
def test_f001_f003_embedded_newline_guard_in_source():
    """profile_builder.cpp must contain the has_embedded_newlines guard."""
    src = PROFILE_BUILDER.read_text(encoding="utf-8", errors="replace")
    assert "has_embedded_newlines" in src, (
        "F-001/F-003 regression: has_embedded_newlines guard removed from "
        "profile_builder.cpp"
    )
    assert "if (has_embedded_newlines)" in src, (
        "F-001/F-003 regression: single-thread fallback on embedded-newline "
        "removed from profile_builder.cpp"
    )
    assert "safe_boundaries" in src, (
        "F-001/F-003 regression: safe_boundaries quote-aware pre-scan removed"
    )


def test_f001_f003_multiline_quoted_csv_reads_correctly(tmp_path):
    """CSV with embedded newline inside a quoted field must parse 3 rows
    with zero parse errors (not be silently split mid-record)."""
    import zedda as zd

    # Purposefully write the embedded newline without backslash escaping
    csv_content = (
        "id,description,value\n"
        '1,"hello world",10\n'
        '2,"line one\nline two",20\n'
        '3,"normal",30\n'
    )
    p = tmp_path / "embedded.csv"
    p.write_text(csv_content, encoding="utf-8")
    profile = zd.scan(str(p))
    assert profile.num_rows == 3, (
        f"F-001/F-003 regression: expected 3 rows, got {profile.num_rows}; "
        "embedded-newline inside quoted field is being split/corrupted"
    )
    # No column should have parse errors (old chunking would split mid-field)
    for col in profile.columns:
        # Use canonical model's null_pct.parse_errors (compat layer maps
        # parse_error_count into the null_pct Metric.parse_errors field).
        null_m = col.metrics.get("null_pct")
        parse_errs = null_m.parse_errors if null_m else 0
        assert parse_errs == 0, (
            f"F-001/F-003 regression: column {col.name!r} has {parse_errs} "
            "parse errors; may be a boundary-split regression"
        )


# ─────────────────────────────────────────────────────────────────
# F-014: Categorical drift fields
# Audit claim: distinct_values / distinct_overflowed not exposed by
# bindings.cpp.
#
# Current state (verified 2026-10-06, bindings.cpp lines 68-70):
#   def_prop_ro("distinct_values")   → c.top_values
#   def_prop_ro("distinct_overflowed") → !c.exact_unique_valid
# DISTINCT_VALUES_CAP = 100,000 (column_accumulator.hpp:108).
# compute_category_diff() in _compare.py lines 300-408 reads these
# fields and returns INDETERMINATE when overflowed.
# STATUS: RESOLVED.
# ─────────────────────────────────────────────────────────────────
def test_f014_bindings_expose_distinct_aliases():
    """bindings.cpp must expose distinct_values and distinct_overflowed."""
    src = BINDINGS.read_text(encoding="utf-8", errors="replace")
    assert '"distinct_values"' in src, (
        "F-014 regression: distinct_values alias removed from bindings.cpp"
    )
    assert '"distinct_overflowed"' in src, (
        "F-014 regression: distinct_overflowed alias removed from bindings.cpp"
    )


def test_f014_compute_category_diff_overflow_is_indeterminate():
    """compute_category_diff must return INDETERMINATE when distinct_overflowed."""
    from zedda._compare import compute_category_diff

    class FakeCol:
        def __init__(self, name, dv, ov, ua=0, tc=100):
            self.name = name
            self.type_str = "str"
            self.distinct_values = dv
            self.distinct_overflowed = ov
            self.unique_approx = ua
            self.total_count = tc

    # Overflowed
    r = compute_category_diff(
        [FakeCol("c", [], True, 80)], [FakeCol("c", [], True, 90)]
    )
    assert r[0]["status"] == "INDETERMINATE", (
        f"Expected INDETERMINATE got {r[0]['status']!r}"
    )

    # Non-overflowed with data
    r2 = compute_category_diff(
        [FakeCol("c", ["A", "B", "C"], False)], [FakeCol("c", ["A", "B", "D"], False)]
    )
    assert r2[0]["status"] == "EXACT"
    assert r2[0]["new_in_b"] == ["D"]
    assert r2[0]["missing_in_b"] == ["C"]

    # Non-overflowed but empty distinct_values with rows > 0 → INDETERMINATE
    r3 = compute_category_diff(
        [FakeCol("c", [], False, 5, 100)], [FakeCol("c", [], False, 7, 100)]
    )
    assert r3[0]["status"] == "INDETERMINATE", (
        f"F-014 regression: empty distinct_values+total>0 should be INDETERMINATE, got {r3[0]['status']!r}"
    )


def test_f014_categorical_drift_via_real_scan(tmp_path):
    """End-to-end: categoricals with differing values detected correctly."""
    import zedda as zd

    c1 = tmp_path / "a.csv"
    c2 = tmp_path / "b.csv"
    c1.write_text("status\nactive\nactive\ninactive\n", encoding="utf-8")
    c2.write_text("status\nactive\nactive\npending\n", encoding="utf-8")
    p1 = zd.scan(str(c1))
    p2 = zd.scan(str(c2))

    from zedda._compare import compute_category_diff

    diffs = compute_category_diff(p1.columns, p2.columns)
    assert any(d["col_name"] == "status" for d in diffs), (
        "F-014: no categorical diff result for 'status' column"
    )
    status_diff = next(d for d in diffs if d["col_name"] == "status")
    # "pending" is new in b; "inactive" is missing from b
    assert "pending" in status_diff["new_in_b"], (
        f"Expected 'pending' in new_in_b: {status_diff}"
    )
    assert "inactive" in status_diff["missing_in_b"], (
        f"Expected 'inactive' in missing_in_b: {status_diff}"
    )


# ─────────────────────────────────────────────────────────────────
# F-024 / F-025 / F-038: Validation fail-closed
# Audit claim: validation could PASS without evaluating a rule;
# approximate uniqueness (HLL) could pass exact-uniqueness contract.
#
# Current state (verified 2026-10-06):
#   - DISTINCT_VALUES_CAP = 100,000; for <=100k distinct strings, the
#     C++ kernel sets exact_unique_valid=true and unique_exact = exact
#     count.  For >100k rows: exact_unique_valid stays false, compat.py
#     uses MetricStatus.APPROXIMATE (lines 116-124), and _validate.py
#     lines 471-495 return INDETERMINATE for approximate uniqueness.
#   - RuleResult.__post_init__ (models.py:347-352) structurally enforces
#     that evaluated=False is always coerced to INDETERMINATE.
# STATUS: RESOLVED.  The fail-closed invariant is structurally enforced.
# ─────────────────────────────────────────────────────────────────
def test_f024_f025_approximate_uniqueness_is_indeterminate_in_compat():
    """When exact_unique_valid=False, _compat.py must set APPROXIMATE not EXACT."""
    from zedda._models import MetricStatus

    compat_src = COMPAT_PY.read_text(encoding="utf-8")
    # The else branch must assign APPROXIMATE status (not EXACT) when
    # exact_unique_valid is False.
    assert "MetricStatus.APPROXIMATE" in compat_src, (
        "F-024/F-025 regression: MetricStatus.APPROXIMATE no longer used in "
        "_compat.py — approximate uniqueness may be mis-classified as EXACT"
    )


def test_f024_f025_validate_is_unique_indeterminate_on_approximate(tmp_path):
    """is_unique rule must return INDETERMINATE when uniqueness metric is APPROXIMATE.
    This exercises the _validate.py logic path directly, simulating a sampled/
    approximate profile.
    """
    from zedda._validate import validate
    from zedda._models import ValidationStatus, MetricStatus, Metric, Coverage

    class FakeCol:
        name = "id"
        type_str = "str"
        null_pct = 0.0
        val_min = None
        val_max = None
        # Approximate uniqueness (HLL) — exact_unique_valid = False
        unique_exact = -1
        exact_unique_valid = False
        unique_approx = 999
        top_values = []
        distinct_values = []
        distinct_overflowed = False
        min_str_len = None
        max_str_len = None
        total_count = 1000
        unsupported_types = []
        metrics = {
            "unique": Metric(
                value=999,
                status=MetricStatus.APPROXIMATE,
                coverage=Coverage(rows_examined=1000, rows_total=1000),
                method="HLL",
            )
        }

    class FakeProfile:
        file_name = "test"
        columns = [FakeCol()]
        num_rows = 1000

    report = validate(
        data=None, rules={"id": {"is_unique": True}}, profile=FakeProfile()
    )
    col = next(c for c in report.columns if c.column == "id")
    # Approximate evidence → INDETERMINATE (not PASS and not FAIL)
    assert col.status == ValidationStatus.INDETERMINATE, (
        f"F-024/F-025 regression: approximate uniqueness returned {col.status.name}, "
        "expected INDETERMINATE"
    )
    assert not col.rule_results["is_unique"].evaluated, (
        "F-025 regression: rule evaluated=True on approximate uniqueness — "
        "must be False (INDETERMINATE)"
    )


def test_f038_rule_result_evaluated_false_is_always_indeterminate():
    """RuleResult with evaluated=False must be INDETERMINATE regardless of status arg."""
    from zedda._models import RuleResult, ValidationStatus

    # Try to construct a PASS with evaluated=False — __post_init__ must coerce it
    r = RuleResult(evaluated=False, status=ValidationStatus.PASS)
    assert r.status == ValidationStatus.INDETERMINATE, (
        "F-038 regression: RuleResult(evaluated=False, status=PASS) is no longer "
        "coerced to INDETERMINATE in __post_init__"
    )

    r2 = RuleResult(evaluated=False, status=ValidationStatus.FAIL)
    assert r2.status == ValidationStatus.INDETERMINATE, (
        "F-038 regression: RuleResult(evaluated=False, status=FAIL) must be INDETERMINATE"
    )


def test_f038_no_unevaluated_pass_in_validation_with_missing_evidence():
    """Validate with missing evidence must produce INDETERMINATE, never PASS."""
    from zedda._validate import validate
    from zedda._models import ValidationStatus

    class EmptyCol:
        name = "ghost"
        null_pct = None
        val_min = None
        val_max = None
        unique_exact = -1
        exact_unique_valid = False
        unique_approx = None
        top_values = []
        distinct_values = []
        distinct_overflowed = False
        min_str_len = None
        max_str_len = None
        total_count = 100
        unsupported_types = []
        metrics = {}

    class FakeProfile:
        file_name = "ghost_test"
        columns = [EmptyCol()]
        num_rows = 100

    report = validate(
        data=None,
        rules={"ghost": {"max_null_pct": 0.0, "is_unique": True}},
        profile=FakeProfile(),
    )
    for col in report.columns:
        for rule_name, rr in col.rule_results.items():
            assert not (rr.status == ValidationStatus.PASS and not rr.evaluated), (
                f"F-038 regression: rule {rule_name!r} is PASS with evaluated=False — "
                "fail-open behavior detected"
            )


# ─────────────────────────────────────────────────────────────────
# F-040: Duplicate scan() implementations
# Audit claim: competing scan() in __init__.py and _scan.py with
# divergent behavior.
#
# Current state (verified 2026-10-06):
#   - __init__.py line 12: `from ._engine import scan` → canonical scan.
#   - __init__.py line 20: `from . import _scan` → module import (helpers).
#   - _scan.py: defines count_lines() and scan_arrow() only; NO top-level
#     scan() function.
#   - _engine.py: defines the one canonical scan().
# STATUS: RESOLVED — one canonical scan() implementation.
# ─────────────────────────────────────────────────────────────────
def test_f040_no_duplicate_scan_in_scan_py():
    """_scan.py must NOT define a top-level scan() function."""
    src = SCAN_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    top_funcs = [
        n.name
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.col_offset == 0
    ]
    assert "scan" not in top_funcs, (
        "F-040 regression: _scan.py defines a top-level scan() — "
        "two competing implementations detected"
    )


def test_f040_public_scan_is_engine_scan():
    """zd.scan must be the same object as _engine.scan."""
    import zedda as zd
    from zedda._engine import scan as engine_scan

    assert zd.scan is engine_scan, (
        "F-040 regression: zd.scan diverged from _engine.scan — "
        "a competing implementation may have been introduced"
    )
