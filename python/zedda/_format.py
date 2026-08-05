"""
zedda._format — shared formatting and display helpers.

FIX P-M2 / Batch 7: Extracted from __init__.py to reduce module size
and eliminate 6× duplicated copies of these helpers across the codebase.
Internal — not part of the public API.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


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
    filled = max(0, min(10, int(score) // 10))
    try:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        "█░".encode(encoding)
        return "█" * filled + "░" * (10 - filled)
    except (UnicodeEncodeError, LookupError):
        return "=" * filled + "-" * (10 - filled)


def render_sparkline_text(histogram_bins: list[int] | tuple | Any) -> str:
    """Render an 8-character UTF-8 sparkline from 16 numeric histogram bins.

    Uses Unicode block characters:  ▂▃▄▅▆▇█
    """
    if not histogram_bins or not any(histogram_bins):
        return "[dim]—[/dim]"

    raw_bins = list(histogram_bins)
    if len(raw_bins) == 16:
        bins = [raw_bins[i] + raw_bins[i + 1] for i in range(0, 16, 2)]
    else:
        bins = raw_bins

    try:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        enc_norm = encoding.lower().replace("-", "").replace("_", "")
        if enc_norm in ("cp1252", "cp437", "cp850", "ascii", "charmap"):
            blocks = (" ", ".", ":", "-", "+", "=", "#", "%", "@")
        else:
            " ▂▃▄▅▆▇█".encode(encoding)
            blocks = (" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█")
    except (UnicodeEncodeError, LookupError):
        blocks = (" ", ".", ":", "-", "+", "=", "#", "%", "@")

    max_val = max(bins)
    if max_val <= 0:
        return "[dim]—[/dim]"

    chars = []
    for count in bins:
        if count <= 0:
            chars.append(" ")
        else:
            idx = max(1, min(8, int(round((count / max_val) * 8))))
            chars.append(blocks[idx])
    return "".join(chars)


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


def safe_symbol(sym: str, fallback: str) -> str:
    """Return sym if the current stdout encoding supports it, else fallback."""
    try:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        enc_norm = encoding.lower().replace("-", "").replace("_", "")
        if enc_norm in ("cp1252", "cp437", "cp850", "ascii", "charmap"):
            if any(ord(c) > 127 for c in sym):
                return fallback
        sym.encode(encoding)
        return sym
    except (UnicodeEncodeError, LookupError):
        return fallback


def render_shape_descriptor(col: Any, total_rows: int = 0) -> str:
    """Render a hybrid shape descriptor (classification label for continuous, percentage split for discrete)."""
    try:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        enc_norm = encoding.lower().replace("-", "").replace("_", "")
        has_unicode = enc_norm not in ("cp1252", "cp437", "cp850", "ascii", "charmap")
    except (UnicodeEncodeError, LookupError):
        has_unicode = False

    uniq = getattr(col, "unique_exact", None)
    if uniq is None or getattr(col, "exact_numeric_overflowed", False):
        uniq = getattr(col, "unique_approx", 0)

    non_null = getattr(col, "non_null_count", 0)
    if non_null <= 0 and total_rows > 0:
        non_null = int(round(total_rows * (1.0 - getattr(col, "null_pct", 0.0) / 100.0)))

    v_sep = "│" if has_unicode else "|"

    # 1. Discrete / Binary Column handling (unique <= 5)
    if uniq > 0 and uniq <= 5:
        mean_v = getattr(col, "mean", None)
        val_min = getattr(col, "val_min", None)
        val_max = getattr(col, "val_max", None)

        if uniq == 2 and val_min == 0 and val_max == 1 and mean_v is not None and 0 <= mean_v <= 1:
            pct1 = int(round(mean_v * 100))
            pct0 = 100 - pct1
            return f"0: {pct0}% {v_sep} 1: {pct1}%"

        bins = [b for b in getattr(col, "histogram_bins", []) if b > 0]
        if len(bins) == 2 and non_null > 0:
            pct0 = int(round(bins[0] / non_null * 100))
            pct1 = 100 - pct0
            return f"0: {pct0}% {v_sep} 1: {pct1}%"
        elif len(bins) == 3 and non_null > 0:
            pct0 = int(round(bins[0] / non_null * 100))
            pct1 = int(round(bins[1] / non_null * 100))
            pct2 = max(0, 100 - pct0 - pct1)
            return f"1: {pct0}% {v_sep} 2: {pct1}% {v_sep} 3: {pct2}%"

    # 2. High Cardinality / ID Column handling
    if total_rows > 0 and (uniq >= total_rows or getattr(col, "is_high_cardinality", False)):
        icon = "▰ " if has_unicode else ""
        return f"{icon}Uniform"

    # 3. Continuous Column handling via Skewness & Distribution
    skew = getattr(col, "skewness", 0.0)

    if skew > 1.2:
        icon = "📉 " if has_unicode else ""
        return f"{icon}Right-Skewed"
    elif skew < -1.2:
        icon = "📉 " if has_unicode else ""
        return f"{icon}Left-Skewed"
    elif -0.5 <= skew <= 0.5:
        icon = "📈 " if has_unicode else ""
        return f"{icon}Normal"
    else:
        icon = "📉 " if has_unicode else ""
        return f"{icon}Skewed"

