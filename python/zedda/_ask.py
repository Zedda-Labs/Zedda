"""
zedda._ask — natural language question answering logic.

FIX Batch 32 / P-M1: Extracted from __init__.py to reduce module size.
Contains the pure pattern-matching logic — no Rich console dependency.
The presentation layer (Rich rendering) stays in __init__.py.

Internal — not part of the public API.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# FIX P-M19: Hoist regex compilation to module scope.
_SINGLE_COL_PATTERNS = [
    (re.compile(r"mean\s+(?:of\s+)?(.+)", re.I), "mean"),
    (re.compile(r"null\s+(?:rate|pct|percent)\s+(?:of\s+)?(.+)", re.I), "null_pct"),
    (re.compile(r"type\s+(?:of\s+)?(.+)", re.I), "type_str"),
    (re.compile(r"min(?:imum)?\s+(?:of\s+)?(.+)", re.I), "val_min"),
    (re.compile(r"max(?:imum)?\s+(?:of\s+)?(.+)", re.I), "val_max"),
    (re.compile(r"stddev\s+(?:of\s+)?(.+)", re.I), "stddev"),
    (re.compile(r"skewness\s+(?:of\s+)?(.+)", re.I), "skewness"),
]


def sanitize_question(q: str) -> str:
    """Strip prompt-injection chars, truncate to 500, raise if empty.

    SEC-Q04: Question sanitization to prevent prompt injection.
    """
    if not q or not q.strip():
        raise ValueError("Question cannot be empty.")
    # Remove control characters except whitespace
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", q)
    # Truncate to 500 chars
    cleaned = cleaned[:500].strip()
    if not cleaned:
        raise ValueError("Question is empty after sanitization.")
    return cleaned


def find_column_by_hint(p: Any, hint: str) -> Any | None:
    """Find a column matching a user-provided hint.

    Tries exact match first, then case-insensitive, then substring.
    Returns the ColumnProfile or None.
    """
    hint_l = hint.lower().strip()
    # Exact match
    for col in p.columns:
        if col.name == hint:
            return col
    # Case-insensitive exact
    for col in p.columns:
        if col.name.lower() == hint_l:
            return col
    # Substring match
    for col in p.columns:
        if hint_l in col.name.lower():
            return col
    return None


def answer_single_col_stat(p: Any, question: str) -> tuple[str, bool] | None:
    """Answer 'mean of X', 'null rate of X', etc.

    Returns (answer_text, show_fix_tip) or None if no pattern matches.
    """
    for pat, attr in _SINGLE_COL_PATTERNS:
        m = pat.search(question)
        if m:
            col_hint = m.group(1).strip().rstrip("?").strip()
            col = find_column_by_hint(p, col_hint)
            if col is None:
                return f"Column '{col_hint}' not found.", False
            val = getattr(col, attr, None)
            if val is None:
                return f"{attr} is not available for column '{col.name}'.", False
            # Format the value
            if attr == "type_str":
                return f"Column '{col.name}' has type: {val}", False
            if attr == "null_pct":
                return f"Column '{col.name}' null rate: {val:.1f}%", True
            if isinstance(val, float):
                return f"Column '{col.name}' {attr}: {val:.4f}", False
            return f"Column '{col.name}' {attr}: {val}", False
    return None


def answer_row_count(p: Any, question: str) -> str | None:
    """Answer 'how many rows', 'row count', etc."""
    q_l = question.lower()
    if any(
        kw in q_l for kw in ("how many rows", "row count", "number of rows", "num rows")
    ):
        return f"The dataset has {p.num_rows:,} rows."
    return None


def answer_col_count(p: Any, question: str) -> str | None:
    """Answer 'how many columns', 'column count', etc."""
    q_l = question.lower()
    if any(
        kw in q_l
        for kw in ("how many columns", "column count", "number of columns", "num cols")
    ):
        return f"The dataset has {p.num_cols} columns."
    return None


def answer_null_summary(p: Any, question: str) -> str | None:
    """Answer 'how many nulls', 'null summary', etc."""
    q_l = question.lower()
    if any(
        kw in q_l
        for kw in ("how many nulls", "null summary", "missing values", "null count")
    ):
        high_null = [c for c in p.columns if c.null_pct > 5]
        if not high_null:
            return f"No significant nulls found. Overall null rate: {p.overall_null_pct:.1f}%"
        lines = [f"Overall null rate: {p.overall_null_pct:.1f}%"]
        for c in sorted(high_null, key=lambda c: c.null_pct, reverse=True)[:5]:
            lines.append(f"  {c.name}: {c.null_pct:.1f}%")
        return "\n".join(lines)
    return None


def answer_correlation_summary(p: Any, question: str) -> str | None:
    """Answer 'correlations', 'correlated columns', etc."""
    q_l = question.lower()
    if any(kw in q_l for kw in ("correlation", "correlated", "collinear")):
        if not p.correlations:
            return "No strong correlations found (|r| >= 0.7)."
        lines = [f"Found {len(p.correlations)} correlated pair(s):"]
        for cr in p.correlations[:10]:
            lines.append(f"  {cr.col_a} ↔ {cr.col_b}  r={cr.r:+.2f}  ({cr.strength})")
        return "\n".join(lines)
    return None


def answer_offline(p: Any, question: str) -> tuple[str, bool, dict] | None:
    """Try all offline patterns. Returns (answer, show_fix_tip, kwargs) or None.

    This is the main entry point for offline question answering.
    Tries each pattern in order; returns the first match.
    """
    # Single-column stat lookups
    result = answer_single_col_stat(p, question)
    if result is not None:
        return result[0], result[1], {}

    # Row count
    ans = answer_row_count(p, question)
    if ans is not None:
        return ans, False, {}

    # Column count
    ans = answer_col_count(p, question)
    if ans is not None:
        return ans, False, {}

    # Null summary
    ans = answer_null_summary(p, question)
    if ans is not None:
        return ans, True, {}

    # Correlation summary
    ans = answer_correlation_summary(p, question)
    if ans is not None:
        return ans, False, {}

    # No pattern matched
    return None
