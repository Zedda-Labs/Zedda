"""
zedda._format — shared formatting and display helpers.

FIX P-M2 / Batch 7: Extracted from __init__.py to reduce module size
and eliminate 6× duplicated copies of these helpers across the codebase.
Internal — not part of the public API.
"""

from __future__ import annotations

from pathlib import Path


def format_num(val: float, is_integer: bool = False) -> str:
    """Format a numeric value for clean terminal display."""
    if val == 0.0:
        return "0"
    if is_integer:
        return f"{int(val):,}"
    abs_val = abs(val)
    if abs_val >= 1_000_000:
        return f"{val:,.0f}"
    elif abs_val >= 1_000:
        return f"{val:,.1f}"
    elif abs_val >= 1:
        return f"{val:.4f}"
    elif abs_val >= 0.001:
        return f"{val:.6f}"
    else:
        return f"{val:.2e}"


def format_ci(val: float) -> str:
    """Format a confidence-interval value."""
    if val == 0.0:
        return "0"
    abs_val = abs(val)
    if abs_val >= 1_000:
        return f"{val:,.1f}"
    elif abs_val >= 1:
        return f"{val:.1f}"
    elif abs_val >= 0.01:
        return f"{val:.2f}"
    else:
        return f"{val:.2g}"


def format_scan_time(ms: float) -> str:
    """Format a scan time in ms as either seconds or ms."""
    return f"{ms / 1000:.1f} sec" if ms >= 10_000 else f"{ms:.0f} ms"


def quality_label(score: int | float) -> tuple[str, str]:
    """Return (rich_color, label) for a quality score 0-100.

    Replaces 6 duplicated copies of this threshold logic.
    """
    if score >= 95:
        return "cyan", "PRISTINE"
    if score >= 80:
        return "green", "GOOD"
    if score >= 60:
        return "yellow", "FAIR"
    return "red", "POOR"


def render_quality_bar(score: int | float) -> str:
    """Render a 10-character progress bar for a quality score 0-100.

    Replaces 4 duplicated copies of this bar-rendering logic.
    """
    filled = int(score) // 10
    return "=" * filled + "-" * (10 - filled)


def compute_display_name(path, is_temp: bool, label: str = "<DataFrame>") -> str:
    """Compute the display name for a file/DataFrame input.

    Replaces 6 duplicated copies of this conditional across
    profile/compare/fix/ml_ready/warnings/clean.
    """
    if is_temp:
        return label
    if isinstance(path, (str, Path)):
        return Path(path).name
    return label


def safe_col_name(name: str) -> str:
    """Return repr(name) — safe for use inside generated Python code.

    SEC-P01: Uses repr() to properly escape all special characters,
    preventing code injection via malicious column names in CSV files.
    """
    return repr(name)
