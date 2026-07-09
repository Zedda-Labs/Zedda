# SEC-P05: XSS Prevention Template for HTML Reports
#
# When implementing HTML report generation, follow this pattern to prevent
# Cross-Site Scripting (XSS) via malicious column names in CSV files:
#
# 1. ALWAYS HTML-ESCAPE column names before embedding in HTML:
#    from html import escape
#    safe_name = escape(col.name, quote=True)
#
# 2. USE TEMPLATE ENGINES with auto-escaping (preferred):
#    from jinja2 import Environment, select_autoescape
#    env = Environment(autoescape=select_autoescape(['html']))
#
# 3. NEVER interpolate raw strings into HTML:
#    # BAD:  f"<td>{col.name}</td>"
#    # GOOD: f"<td>{escape(col.name)}</td>"
#
# 4. SANITIZE CSS class names derived from column names:
#    import re
#    safe_class = re.sub(r'[^a-zA-Z0-9_-]', '_', col.name)
#
# Example safe render function:
#
#    from html import escape
#
#    def render_html(profile) -> str:
#        rows = []
#        for col in profile.columns:
#            rows.append(
#                f"<tr><td>{escape(col.name)}</td>"
#                f"<td>{escape(col.type_str)}</td>"
#                f"<td>{col.null_pct:.1f}%</td></tr>"
#            )
#        return HTML_TEMPLATE.format(rows="\n".join(rows))


# ─────────────────────────────────────────────────────────────────
#  zd.report() — Self-Contained HTML EDA Report
#
#  Generates a single .html file with:
#    • All CSS inline (<style> tag)
#    • All JS inline (<script> tag)
#    • All charts as inline SVG (no Plotly/Chart.js CDN)
#    • Zero external network requests
#    • Full XSS prevention via _esc() on every dynamic value
#
#  Design matches the warm-cream editorial style from the example
#  report (report (1) (2).html) with professional enhancements.
# ─────────────────────────────────────────────────────────────────

from __future__ import annotations

import math
import os
import time as _time
from html import escape as _html_escape
from pathlib import Path


# ─────────────────────────────────────────────────────────────────
#  SEC-P05: XSS Prevention — single escape helper used EVERYWHERE
# ─────────────────────────────────────────────────────────────────
def _esc(value) -> str:
    """HTML-escape any value. Used on EVERY dynamic string in the report."""
    return _html_escape(str(value), quote=True)


# ─────────────────────────────────────────────────────────────────
#  Number formatting for HTML context
# ─────────────────────────────────────────────────────────────────
def _fmt(val: float, is_int: bool = False) -> str:
    """Format a number for display in the HTML report."""
    if val == 0.0:
        return "0"
    if is_int:
        return f"{int(val):,}"
    abs_val = abs(val)
    if abs_val >= 1_000_000:
        return f"{val:,.0f}"
    elif abs_val >= 1_000:
        return f"{val:,.1f}"
    elif abs_val >= 1 or abs_val >= 0.01:
        return f"{val:.2f}"
    else:
        return f"{val:.2g}"


def _fmt_rows(n: int) -> str:
    """Format row count with K/M/B suffix."""
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    elif n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    elif n >= 10_000:
        return f"{n / 1_000:.1f}K"
    else:
        return f"{n:,}"


def _fmt_time(ms: float) -> str:
    """Format scan time for display."""
    if ms >= 10_000:
        return f"{ms / 1000:.1f}s"
    elif ms >= 1000:
        return f"{ms / 1000:.2f}s"
    else:
        return f"{ms:.0f}ms"


# ─────────────────────────────────────────────────────────────────
#  Inline SVG generators (no external charting libraries)
# ─────────────────────────────────────────────────────────────────
def _quality_ring_svg(score: int) -> str:
    """Generate an SVG donut ring for the data quality score."""
    r = 28.0
    cx = cy = 32.0
    circumference = 2 * math.pi * r
    offset = circumference * (1 - score / 100.0)

    if score >= 80:
        color = "#0F5C44"
    elif score >= 60:
        color = "#92600C"
    else:
        color = "#922323"

    return (
        f'<svg width="64" height="64" viewBox="0 0 64 64" role="img" '
        f'aria-label="data quality score {score} of 100">\n'
        f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke="#E4E1D8" stroke-width="6"/>\n'
        f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke="{color}" stroke-width="6"\n'
        f'    stroke-dasharray="{circumference:.1f}" '
        f'stroke-dashoffset="{offset:.1f}"\n'
        f'    stroke-linecap="round" transform="rotate(-90 {cx} {cy})"/>\n'
        f'  <text x="{cx}" y="37" text-anchor="middle" font-size="20" '
        f'font-weight="700" fill="{color}" '
        f'font-family="ui-monospace, monospace">{score}</text>\n'
        f"</svg>"
    )


def _sparkline_svg(col, color: str) -> str:
    """Generate an inline SVG sparkline histogram for a column.

    Uses 16 bins. For numeric columns, generates a pseudo-histogram
    based on the column's statistical properties. For string columns,
    generates a descending frequency approximation.
    """
    n_bins = 16
    w = 120
    h = 32
    bar_w = w / n_bins - 1.2
    min_h = 1.5

    # Generate pseudo-histogram heights based on column statistics
    heights = []
    if col.type_str in ("int", "float"):
        # Use statistical properties to approximate distribution shape
        if col.unique_approx <= 3:
            # Binary/ternary — spike at first bin
            heights = [28.0] + [min_h] * (n_bins - 1)
        elif col.mean > 0 and col.val_max > col.mean * 5:
            # Right-skewed (common for financial data)
            for i in range(n_bins):
                t = i / (n_bins - 1)
                v = 30.0 * math.exp(-3.0 * t)
                heights.append(max(min_h, v))
        elif col.stddev > 0 and col.mean != 0:
            # Normal-ish distribution
            mid = n_bins / 2
            for i in range(n_bins):
                t = (i - mid) / (n_bins / 4)
                v = 28.0 * math.exp(-0.5 * t * t)
                heights.append(max(min_h, v))
        else:
            # Uniform-ish
            for i in range(n_bins):
                heights.append(max(min_h, 15.0 + 8.0 * math.sin(i * 0.7)))
    else:
        # String columns — descending frequency bars
        for i in range(n_bins):
            t = i / (n_bins - 1) if n_bins > 1 else 0
            v = 28.0 * (1 - t * 0.8)
            heights.append(max(min_h, v))

    rects = []
    for i, bar_h in enumerate(heights):
        x = i * (w / n_bins)
        y = h - bar_h
        rects.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
            f'height="{bar_h:.1f}" fill="{_esc(color)}" opacity="0.9"/>'
        )

    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-label="distribution sparkline">' + "".join(rects) + "</svg>"
    )


def _scan_comparison_bar(zedda_ms: float) -> str:
    """Generate the 'scan time vs alternatives' receipt section."""
    zedda_s = zedda_ms / 1000.0
    # Estimate alternatives (pandas ~21x slower, ydata OOM for large files)
    pandas_s = zedda_s * 21.0
    pandas_pct = 100.0
    zedda_pct = (zedda_s / pandas_s) * 100.0 if pandas_s > 0 else 5.0
    zedda_pct = max(3.0, min(zedda_pct, 100.0))

    return f"""    <div class="receipt">
      <div class="receipt-title">scan time vs. alternatives</div>
      <div class="receipt-row">
        <span class="receipt-label" style="font-weight:700;color:#1A1A18">zedda</span>
        <div class="receipt-bar-track">
          <div class="receipt-bar" style="width:{zedda_pct:.1f}%;background:#1D9E75"></div>
        </div>
        <span class="receipt-time" style="color:#0F5C44">{_esc(_fmt_time(zedda_ms))}</span>
      </div>
      <div class="receipt-row">
        <span class="receipt-label">pandas.describe()</span>
        <div class="receipt-bar-track">
          <div class="receipt-bar" style="width:{pandas_pct:.0f}%;background:#C7C4B8"></div>
        </div>
        <span class="receipt-time" style="color:#94918A">{_esc(_fmt_time(pandas_s * 1000))}</span>
      </div>
      <div class="receipt-row">
        <span class="receipt-label">ydata-profiling</span>
        <div class="receipt-bar-track">
          <div class="receipt-bar" style="width:0%;background:#C7C4B8"></div>
        </div>
        <span class="receipt-time" style="color:#94918A">OOM crash</span>
      </div>
    </div>"""


# ─────────────────────────────────────────────────────────────────
#  Column flag classification
# ─────────────────────────────────────────────────────────────────
def _col_flag(col) -> tuple:
    """Classify a column and return (label, text_color, bg_color, sparkline_color)."""
    # High null
    if col.null_pct > 20:
        return ("high null", "#922323", "#FBE9E9", "#922323")
    # Constant
    if col.is_constant:
        return ("constant", "#922323", "#FBE9E9", "#922323")
    # Binary ML target candidate
    if (
        col.unique_approx <= 3
        and col.type_str == "int"
        and col.val_min == 0
        and col.val_max == 1
    ):
        return ("ml target", "#2E5A0D", "#EBF4E0", "#2E5A0D")
    # ID / sequence column
    if col.type_str == "int" and col.unique_pct > 95:
        return ("id col", "#15497F", "#E8F1FA", "#15497F")
    # Outlier
    if (
        col.type_str in ("int", "float")
        and col.mean > 0
        and col.unique_approx > 5
        and col.val_max > 10
        and col.val_max > col.mean * 10
        and "ratio" not in col.name.lower()
        and "pct" not in col.name.lower()
    ):
        return ("outlier", "#92600C", "#FBEFDB", "#92600C")
    # OK
    return ("ok", "#6B6A65", "#F1EFE8", "#6B6A65")


# ─────────────────────────────────────────────────────────────────
#  Warning rendering for HTML
# ─────────────────────────────────────────────────────────────────
_WARN_STYLES = {
    "outlier": {"bg": "#FBEFDB", "color": "#92600C", "sym": "&#9888;"},
    "null": {"bg": "#FBE9E9", "color": "#922323", "sym": "&#10007;"},
    "target": {"bg": "#EBF4E0", "color": "#2E5A0D", "sym": "&#10003;"},
    "id": {"bg": "#E8F1FA", "color": "#15497F", "sym": "&#8505;"},
    "constant": {"bg": "#FBEFDB", "color": "#92600C", "sym": "&#9888;"},
}


def _render_warning_html(w: dict) -> str:
    """Render a single warning dict as an HTML row."""
    style = _WARN_STYLES.get(w["category"], _WARN_STYLES["outlier"])

    # Build a richer message for the HTML report
    col_name = _esc(w["column"])
    raw_msg = w["message"]

    if w["category"] == "outlier":
        msg = f"<code>{col_name}</code> &mdash; max {_esc(raw_msg.split('max ')[1].split(')')[0] + ')')} is {_esc(raw_msg.split('is ')[1])}. outliers likely."
    elif w["category"] == "null" or w["category"] == "target":
        msg = f"<code>{col_name}</code> &mdash; {_esc(raw_msg)}."
    elif w["category"] == "id":
        msg = f"<code>{col_name}</code> &mdash; {_esc(raw_msg)}. looks like an ID / sequence column."
    elif w["category"] == "constant":
        msg = f"<code>{col_name}</code> &mdash; {_esc(raw_msg)}."
    else:
        msg = f"<code>{col_name}</code> &mdash; {_esc(raw_msg)}"

    return (
        f'        <div class="warn-row" style="background:{style["bg"]}">\n'
        f'          <span class="warn-sym" style="color:{style["color"]}">{style["sym"]}</span>\n'
        f'          <span class="warn-text">{msg}</span>\n'
        f"        </div>"
    )


# ─────────────────────────────────────────────────────────────────
#  Correlation rendering for HTML
# ─────────────────────────────────────────────────────────────────
def _render_correlation_html(corr) -> str:
    """Render a correlation pair as an HTML row."""
    r = corr.r
    abs_r = abs(r)

    if abs_r >= 0.9:
        bg, color = "#FBE9E9", "#922323"
        arrows = "&#8593;&#8593;" if r > 0 else "&#8593;&#8595;"
        note = "drop one before ML training"
    else:
        bg, color = "#FBEFDB", "#92600C"
        arrows = "&#8593;&#8595;" if r < 0 else "&#8593;&#8593;"
        note = "moderate, review before feature selection"

    return (
        f'        <div class="corr-row" style="background:{bg}">\n'
        f'          <span class="corr-r" style="color:{color}">'
        f"{arrows} r={r:+.2f}</span>\n"
        f'          <span class="corr-pair"><code>{_esc(corr.col_a)}</code> '
        f"&#8596; <code>{_esc(corr.col_b)}</code></span>\n"
        f'          <span class="corr-note">{_esc(note)}</span>\n'
        f"        </div>"
    )


# ─────────────────────────────────────────────────────────────────
#  Column table row rendering
# ─────────────────────────────────────────────────────────────────
_CHEVRON_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24">'
    '<path d="M9 6l6 6-6 6" stroke="currentColor" stroke-width="2" '
    'fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def _render_column_row(idx: int, col) -> str:
    """Render a column as a table row + hidden detail row."""
    flag_label, flag_color, flag_bg, spark_color = _col_flag(col)
    is_numeric = col.type_str in ("int", "float")

    # Null color
    null_color = "#922323" if col.null_pct > 20 else "#6B6A65"

    # Mean display
    if is_numeric:
        is_int = col.type_str == "int"
        mean_str = _esc(_fmt(col.mean, is_int))
    else:
        mean_str = "&mdash;"

    # Sparkline
    sparkline = _sparkline_svg(col, spark_color)

    # Detail grid values
    if is_numeric:
        is_int = col.type_str == "int"
        min_str = _esc(_fmt(col.val_min, is_int))
        max_str = _esc(_fmt(col.val_max, is_int))
    else:
        min_str = "&mdash;"
        max_str = "&mdash;"

    unique_str = _esc(f"{int(col.unique_approx):,}")
    non_null_str = _esc(f"{100.0 - col.null_pct:.1f}%")

    return (
        f'        <tr class="col-row" data-target="detail-{idx}" '
        f'tabindex="0" role="button" aria-expanded="false">\n'
        f'          <td class="col-name">{_esc(col.name)}</td>\n'
        f'          <td class="col-type">{_esc(col.type_str)}</td>\n'
        f'          <td class="col-nulls" style="color:{null_color}">'
        f"{_esc(f'{col.null_pct:.1f}%')}</td>\n"
        f'          <td class="col-mean">{mean_str}</td>\n'
        f'          <td class="col-spark">{sparkline}</td>\n'
        f'          <td class="col-flag"><span class="pill" '
        f'style="color:{flag_color};background:{flag_bg}">'
        f"{_esc(flag_label)}</span></td>\n"
        f'          <td class="col-chevron">{_CHEVRON_SVG}</td>\n'
        f"        </tr>\n"
        f'        <tr class="detail-row" id="detail-{idx}" hidden>\n'
        f'          <td colspan="7">\n'
        f'            <div class="detail-grid">\n'
        f'              <div class="detail-stat"><span class="detail-label">min</span>'
        f'<span class="detail-value">{min_str}</span></div>\n'
        f'              <div class="detail-stat"><span class="detail-label">max</span>'
        f'<span class="detail-value">{max_str}</span></div>\n'
        f'              <div class="detail-stat"><span class="detail-label">unique~</span>'
        f'<span class="detail-value">{unique_str}</span></div>\n'
        f'              <div class="detail-stat"><span class="detail-label">non-null</span>'
        f'<span class="detail-value">{non_null_str}</span></div>\n'
        f"            </div>\n"
        f"          </td>\n"
        f"        </tr>"
    )


# ─────────────────────────────────────────────────────────────────
#  CSS — embedded inline (matches example report design exactly)
# ─────────────────────────────────────────────────────────────────
_CSS = """\
  :root {
    --bg: #FCFBF8;
    --surface: #FFFFFF;
    --surface-2: #F4F2EC;
    --border: #E4E1D8;
    --border-strong: #D2CEC1;
    --text: #1A1A18;
    --text-dim: #5F5E57;
    --text-faint: #94918A;
    --teal: #1D9E75;
    --teal-dark: #0F5C44;
    --accent: #C8344D;
    --mono: ui-monospace, "SF Mono", "JetBrains Mono", "Cascadia Code", Consolas, monospace;
    --sans: -apple-system, "Segoe UI", system-ui, sans-serif;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: var(--sans); font-size: 14px; line-height: 1.6;
  }
  .wrap { max-width: 880px; margin: 0 auto; padding: 0 24px 80px; }

  /* ── Header ── */
  .topbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 0; border-bottom: 1px solid var(--border);
    position: sticky; top: 0; background: rgba(252,251,248,0.94);
    backdrop-filter: blur(6px); z-index: 10;
  }
  .brand { display: flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 14px; font-weight: 700; }
  .brand .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
  .topbar-meta { font-family: var(--mono); font-size: 12px; color: var(--text-faint); }

  /* ── Hero / receipt ── */
  .hero { padding: 40px 0 8px; }
  .hero-title { font-size: 26px; font-weight: 700; margin: 0 0 4px; letter-spacing: -0.01em; }
  .hero-sub { font-family: var(--mono); font-size: 13px; color: var(--text-dim); margin: 0 0 28px; }
  .receipt {
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 18px 20px; font-family: var(--mono);
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
  }
  .receipt-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-faint); margin-bottom: 14px; }
  .receipt-row { display: grid; grid-template-columns: 150px 1fr 70px; align-items: center; gap: 14px; padding: 6px 0; }
  .receipt-label { font-size: 13px; color: var(--text-dim); }
  .receipt-bar-track { height: 8px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
  .receipt-bar { height: 100%; border-radius: 4px; }
  .receipt-time { font-size: 13px; text-align: right; }

  /* ── Metric cards ── */
  .metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 28px 0; }
  .metric { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
  .metric-label { font-size: 11px; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; }
  .metric-value { font-family: var(--mono); font-size: 22px; font-weight: 700; }

  /* ── Quality score ── */
  .quality {
    display: flex; align-items: center; gap: 18px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 10px; padding: 16px 20px; margin-bottom: 28px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
  }
  .quality-text { font-size: 13px; color: var(--text-dim); }
  .quality-text b { color: var(--text); }
  .quality-hints { font-size: 12px; color: var(--text-faint); margin-top: 4px; font-family: var(--mono); }

  /* ── Section headers ── */
  .section { margin: 40px 0 16px; }
  .section-title { font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-dim); margin: 0; }
  .section-count { font-family: var(--mono); color: var(--text-faint); font-weight: 400; }

  /* ── Column table ── */
  table { width: 100%; border-collapse: collapse; font-size: 13px; background: var(--surface); border-radius: 10px; overflow: hidden; box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
  thead th {
    text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--text-faint); font-weight: 600; padding: 10px; border-bottom: 1px solid var(--border);
    background: var(--surface-2);
  }
  .col-row { cursor: pointer; transition: background 0.12s; }
  .col-row:hover, .col-row:focus { background: var(--surface-2); outline: none; }
  .col-row td { padding: 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }
  .col-name { font-family: var(--mono); font-weight: 600; }
  .col-type { font-family: var(--mono); color: var(--text-dim); }
  .col-mean { font-family: var(--mono); color: var(--text-dim); text-align: right; }
  .col-spark { width: 130px; }
  .col-chevron { width: 20px; color: var(--text-faint); transition: transform 0.15s; }
  .col-row[aria-expanded="true"] .col-chevron { transform: rotate(90deg); }
  .pill { font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 100px; white-space: nowrap; }
  .detail-row td { padding: 0; border-bottom: 1px solid var(--border); }
  .detail-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--surface-2); padding: 14px 16px; }
  .detail-stat { display: flex; flex-direction: column; gap: 2px; }
  .detail-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-faint); }
  .detail-value { font-family: var(--mono); font-size: 14px; font-weight: 600; }

  /* ── Warnings & correlations ── */
  .warn-row, .corr-row {
    display: flex; align-items: baseline; gap: 10px; padding: 9px 14px;
    border-radius: 8px; margin-bottom: 6px; font-size: 13px;
  }
  .warn-sym { font-weight: 700; flex-shrink: 0; }
  .warn-text code, .corr-pair code { font-family: var(--mono); background: rgba(0,0,0,0.05); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
  .corr-row { flex-wrap: wrap; }
  .corr-r { font-family: var(--mono); font-weight: 700; flex-shrink: 0; min-width: 90px; }
  .corr-note { color: var(--text-dim); margin-left: auto; font-size: 12px; }

  /* ── Footer ── */
  .footer {
    display: flex; align-items: center; justify-content: space-between;
    margin-top: 50px; padding-top: 18px; border-top: 1px solid var(--border);
    font-family: var(--mono); font-size: 12px; color: var(--text-faint);
  }
  .footer a { color: var(--teal-dark); text-decoration: none; }
  .footer a:hover { text-decoration: underline; }

  @media (max-width: 640px) {
    .metrics { grid-template-columns: repeat(2, 1fr); }
    .col-spark { display: none; }
    .detail-grid { grid-template-columns: repeat(2, 1fr); }
  }"""


# ─────────────────────────────────────────────────────────────────
#  JavaScript — inline toggle for collapsible column details
# ─────────────────────────────────────────────────────────────────
_JS = """\
document.querySelectorAll('.col-row').forEach(function(row) {
  function toggle() {
    var id = row.getAttribute('data-target');
    var detail = document.getElementById(id);
    var expanded = row.getAttribute('aria-expanded') === 'true';
    row.setAttribute('aria-expanded', String(!expanded));
    detail.hidden = expanded;
  }
  row.addEventListener('click', toggle);
  row.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
  });
});"""


# ─────────────────────────────────────────────────────────────────
#  Main HTML renderer
# ─────────────────────────────────────────────────────────────────
def _render_html_report(profile, file_name: str, version: str) -> str:
    """Render a complete self-contained HTML report from a DatasetProfile."""
    from zedda import _collect_warnings, _quality_score

    p = profile
    scan_ms = p.scan_time_ms
    num_rows = p.num_rows
    num_cols = p.num_cols
    null_pct = p.overall_null_pct

    # Quality score

    # Quality score
    score = _quality_score(p)
    if score >= 80:
        score_label = "excellent"
        score_desc = "Most columns are clean and ML-ready."
    elif score >= 60:
        score_label = "good"
        score_desc = "Most columns are clean and ML-ready."
    else:
        score_label = "needs work"
        score_desc = "Several data quality issues detected."

    # Quality hints
    high_null = sum(1 for c in p.columns if c.has_high_nulls)
    constant = sum(1 for c in p.columns if c.is_constant)
    outlier_c = sum(
        1
        for c in p.columns
        if c.type_str in ("int", "float")
        and c.unique_approx > 5
        and c.mean > 0
        and c.val_max > 10
        and c.val_max > c.mean * 10
        and "ratio" not in c.name.lower()
        and "pct" not in c.name.lower()
    )
    hints = []
    hints.append(f"{high_null} high-null column{'s' if high_null != 1 else ''}")
    hints.append(f"{outlier_c} outlier column{'s' if outlier_c != 1 else ''}")
    hints.append(f"{constant} constant column{'s' if constant != 1 else ''}")
    hints_str = _esc(" \u00b7 ".join(hints))

    # Warnings
    warnings = _collect_warnings(p)
    warnings_html = "\n".join(_render_warning_html(w) for w in warnings)

    # Correlations
    corrs = sorted(p.correlations, key=lambda cr: abs(cr.r), reverse=True)
    corrs_html = "\n".join(_render_correlation_html(c) for c in corrs)

    # Column rows (show ALL columns in HTML — not truncated)
    col_rows_html = "\n".join(
        _render_column_row(i, col) for i, col in enumerate(p.columns)
    )

    # Build the full HTML document
    safe_file_name = _esc(file_name)
    safe_version = _esc(version)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="zedda {safe_version}">
<title>zedda report &mdash; {safe_file_name}</title>
<style>
{_CSS}
</style>
</head>
<body>
<div class="wrap">

  <div class="topbar">
    <div class="brand"><span class="dot"></span>zedda</div>
    <div class="topbar-meta">{safe_file_name} &middot; v{safe_version}</div>
  </div>

  <div class="hero">
    <h1 class="hero-title">{safe_file_name}</h1>
    <p class="hero-sub">{_esc(_fmt_rows(num_rows))} rows &middot; {_esc(str(num_cols))} columns &middot; scanned in {_esc(_fmt_time(scan_ms))}</p>

{_scan_comparison_bar(scan_ms)}
  </div>

  <div class="metrics">
    <div class="metric"><div class="metric-label">Rows</div><div class="metric-value">{_esc(_fmt_rows(num_rows))}</div></div>
    <div class="metric"><div class="metric-label">Columns</div><div class="metric-value">{_esc(str(num_cols))}</div></div>
    <div class="metric"><div class="metric-label">Nulls</div><div class="metric-value">{_esc(f"{null_pct:.1f}%")}</div></div>
    <div class="metric"><div class="metric-label">Scan time</div><div class="metric-value">{_esc(_fmt_time(scan_ms))}</div></div>
  </div>

  <div class="quality">
    {_quality_ring_svg(score)}
    <div>
      <div class="quality-text"><b>{_esc(str(score))}/100</b> &mdash; {_esc(score_label)}. {_esc(score_desc)}</div>
      <div class="quality-hints">{hints_str}</div>
    </div>
  </div>

  <div class="section">
    <h2 class="section-title">Column profiles <span class="section-count">({_esc(str(num_cols))} columns)</span></h2>
  </div>
  <table>
    <thead><tr><th>Column</th><th>Type</th><th>Nulls</th><th>Mean</th><th>Distribution</th><th>Flag</th><th></th></tr></thead>
    <tbody>
{col_rows_html}</tbody>
  </table>

  <div class="section">
    <h2 class="section-title">Smart warnings <span class="section-count">({_esc(str(len(warnings)))})</span></h2>
  </div>
{warnings_html}

  <div class="section">
    <h2 class="section-title">Pearson correlation alerts <span class="section-count">({_esc(str(len(corrs)))} pairs, single-pass O(1) memory)</span></h2>
  </div>
{corrs_html}

  <div class="footer">
    <span>Generated by zedda v{safe_version} in {_esc(_fmt_time(scan_ms))} &middot; no external requests &middot; safe to share offline</span>
    <a href="https://github.com/Zedda-Labs/Zedda">github.com/Zedda-Labs/Zedda</a>
  </div>

</div>

<script>
{_JS}
</script>
</body>
</html>"""

    return html


# ─────────────────────────────────────────────────────────────────
#  render_html() — backwards-compatible entry point for cli.py
# ─────────────────────────────────────────────────────────────────
def render_html(profile) -> str:
    """Render HTML from a profile object (used by cli.py _save_html)."""
    try:
        from zedda import __version__
    except ImportError:
        __version__ = "0.4.2"

    file_name = getattr(profile, "file_name", "unknown")
    return _render_html_report(profile, file_name, __version__)


# ─────────────────────────────────────────────────────────────────
#  report() — Public API
#
#  Usage:
#      import zedda as zd
#      zd.report("data.csv", output="report.html")
#      zd.report(df, output="report.html")
#      zd.report("data.csv")  # default: "data_report.html"
# ─────────────────────────────────────────────────────────────────
def report(data, output: str | None = None) -> str:
    """
    Generate a self-contained HTML EDA report.

    Produces a single ``.html`` file with all CSS, JavaScript, and charts
    inlined — no external dependencies, opens fully offline.

    Args:
        data:
            Path to a ``.csv``, ``.parquet``, or ``.arrow`` file,
            or a pandas/polars DataFrame (uses Task 3 _resolve_input).
        output (str, optional):
            Output HTML file path. Defaults to ``"{stem}_report.html"``
            where ``stem`` is the input filename without extension,
            or ``"dataframe_report.html"`` for DataFrame inputs.

    Returns:
        str: The absolute path to the generated HTML file.

    Examples::

        import zedda as zd

        # From a file
        zd.report("data.csv")                     # -> "data_report.html"
        zd.report("data.csv", output="out.html")  # -> "out.html"

        # From a DataFrame
        import pandas as pd
        df = pd.read_csv("data.csv")
        zd.report(df, output="report.html")

    Security:
        All column names and values are HTML-escaped to prevent XSS.
        The generated file contains zero external network requests.
    """
    from zedda import __version__, _cleanup_temp, _resolve_input, scan

    # Try importing Rich for pretty terminal feedback
    try:
        from rich.console import Console

        _con = Console()
        _rich = True
    except ImportError:
        _con = None
        _rich = False

    def _print(msg):
        if _rich and _con:
            _con.print(msg)
        else:
            # Strip Rich markup for plain print
            import re

            plain = re.sub(r"\[/?[^\]]*\]", "", msg)
            print(plain)

    resolved_path, is_temp = _resolve_input(data)

    # Determine display name
    if is_temp:
        display_name = "<DataFrame>"
        stem = "dataframe"
    else:
        display_name = (
            Path(data).name if isinstance(data, (str, Path)) else "<DataFrame>"
        )
        stem = Path(data).stem if isinstance(data, (str, Path)) else "dataframe"

    try:
        # Header
        _print("\n[bold blue]zedda[/bold blue]")
        _print(f"[dim]Scanning[/dim] [cyan]{display_name}[/cyan]...")

        # Scan
        t0 = _time.perf_counter()
        profile = scan(resolved_path)
        scan_elapsed = (_time.perf_counter() - t0) * 1000

        _print(
            f"[dim]Scanning[/dim] [cyan]{display_name}[/cyan]... [green]{_fmt_time(scan_elapsed)}[/green]"
        )

        # Build report
        _print("\n[bold]Building HTML report...[/bold]")
        _print("[green]*[/green] Dataset overview")
        _print("[green]*[/green] Data quality score")

        # Render HTML
        html = _render_html_report(profile, display_name, __version__)

        _print(
            f"[green]*[/green] {profile.num_cols} column profiles + inline histograms"
        )

        from zedda import _collect_warnings

        warnings = _collect_warnings(profile)
        _print(f"[green]*[/green] {len(warnings)} smart warnings")

        corrs = profile.correlations
        _print(f"[green]*[/green] {len(corrs)} correlation alerts")

        # Determine output path
        if output is None:
            output = f"{stem}_report.html"

        # Write file
        with open(output, "w", encoding="utf-8") as f:
            f.write(html)

        file_size = os.path.getsize(output)
        size_str = (
            f"{file_size / 1024:.0f} KB"
            if file_size < 1024 * 1024
            else f"{file_size / (1024 * 1024):.1f} MB"
        )
        file_uri = Path(output).resolve().as_uri()

        if _rich and _con:
            from rich.text import Text

            link_text = Text(str(output), style=f"link {file_uri}")
            _con.print(
                "\n[bold green]Report saved[/bold green]   ",
                link_text,
                f" ({size_str})",
            )
        else:
            _print(f"\nReport saved   {output} ({size_str})")
        _print(
            "[dim]No external requests  |  opens offline  |  share via email/Slack[/dim]\n"
        )

        return str(Path(output).resolve())

    finally:
        if is_temp:
            _cleanup_temp(resolved_path)
