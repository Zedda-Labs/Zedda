"""
zedda._compare — dataset comparison logic (schema, drift, verdict).

FIX Batch 27 / P-M1: Extracted from __init__.py to reduce module size.
Contains the pure comparison logic — no Rich console dependency.
The presentation layer (Rich rendering) stays in __init__.py.

Internal — not part of the public API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import math

try:
    import numpy as np
    from scipy.stats import wasserstein_distance

    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False


def compute_schema_diff(
    cols_a: list,
    cols_b: list,
    name_a: str = "A",
    name_b: str = "B",
) -> dict:
    """Compute schema differences between two column lists.

    Returns a dict with:
        missing_in_b: list of column names present in A but not B
        missing_in_a: list of column names present in B but not A
        type_mismatches: list of (col_name, type_a, type_b) tuples
        types_match: int — number of columns with matching types
        total_compared: int — total columns compared
    """
    names_a = {c.name: c for c in cols_a}
    names_b = {c.name: c for c in cols_b}
    set_a = set(names_a.keys())
    set_b = set(names_b.keys())

    missing_in_b = sorted(set_a - set_b)
    missing_in_a = sorted(set_b - set_a)
    common = set_a & set_b

    type_mismatches = []
    types_match = 0
    for name in common:
        ta = names_a[name].type_str
        tb = names_b[name].type_str
        if ta != tb:
            type_mismatches.append((name, ta, tb))
        else:
            types_match += 1

    return {
        "missing_in_b": missing_in_b,
        "missing_in_a": missing_in_a,
        "type_mismatches": type_mismatches,
        "types_match": types_match,
        "total_compared": len(common),
    }


def compute_distribution_shift(
    cols_a: list,
    cols_b: list,
) -> list:
    """Compute distribution shift for common numeric columns.

    Uses a shared common support grid for Population Stability Index (PSI)
    and continuous CDF matching for Kolmogorov-Smirnov (KS) and Wasserstein Distance (WD).
    """
    names_a = {c.name: c for c in cols_a}
    names_b = {c.name: c for c in cols_b}
    common = sorted(set(names_a.keys()) & set(names_b.keys()))

    results = []
    for name in common:
        ca = names_a[name]
        cb = names_b[name]
        # Only compare numeric columns
        if ca.type_str not in ("int", "float") or cb.type_str not in ("int", "float"):
            continue
        # Skip ID-like columns (unique_pct > 95)
        if ca.unique_pct > 95 or cb.unique_pct > 95:
            continue
        # Skip binary target columns (0/1)
        if ca.val_min == 0 and ca.val_max == 1 and ca.unique_approx <= 2:
            continue

        mean_a = ca.mean
        mean_b = cb.mean
        shift_abs = mean_b - mean_a

        # Handle negative/zero means correctly
        if mean_a > 0:
            shift_pct = (shift_abs / mean_a) * 100.0
        elif mean_a < 0:
            shift_pct = (shift_abs / abs(mean_a)) * 100.0
        else:
            # mean_a == 0
            shift_pct = 0.0 if mean_b == 0 else float("inf")

        is_stable = abs(shift_pct) < 5.0
        is_shift = abs(shift_pct) >= 10.0

        # Scientific Drift Detection with Shared Support Grid
        ca_bins = list(getattr(ca, "histogram_bins", []))
        cb_bins = list(getattr(cb, "histogram_bins", []))
        ca_min = getattr(ca, "val_min", None)
        ca_max = getattr(ca, "val_max", None)
        cb_min = getattr(cb, "val_min", None)
        cb_max = getattr(cb, "val_max", None)

        sample_size_a = getattr(ca, "total_count", 0)
        sample_size_b = getattr(cb, "total_count", 0)
        min_sample = (
            min(sample_size_a, sample_size_b)
            if (sample_size_a > 0 and sample_size_b > 0)
            else max(sample_size_a, sample_size_b)
        )

        if min_sample < 30:
            uncertainty = "HIGH"
        elif min_sample < 500:
            uncertainty = "MODERATE"
        else:
            uncertainty = "LOW"

        psi = 0.0
        ks_stat = 0.0
        wd = 0.0
        drift_status = "EXACT"
        drift_reason = None

        has_bins = bool(ca_bins and cb_bins and sum(ca_bins) > 0 and sum(cb_bins) > 0)
        has_ranges = (
            ca_min is not None
            and ca_max is not None
            and cb_min is not None
            and cb_max is not None
        )

        if not has_bins or not has_ranges:
            drift_status = "INDETERMINATE"
            drift_reason = "Insufficient histogram bin or range evidence in profile"
            uncertainty = "HIGH"
        elif ca_min == ca_max and cb_min == cb_max:
            # Point mass distributions
            if ca_min == cb_min:
                psi = 0.0
                ks_stat = 0.0
                wd = 0.0
            else:
                psi = 2.0  # Divergent point masses
                ks_stat = 1.0
                wd = float(abs(cb_min - ca_min))
        else:
            global_min = min(ca_min, cb_min)
            global_max = max(ca_max, cb_max)

            # Define edges for each distribution
            edges_a = (
                [
                    ca_min + i * (ca_max - ca_min) / len(ca_bins)
                    for i in range(len(ca_bins) + 1)
                ]
                if ca_max > ca_min
                else [ca_min, ca_max]
            )
            edges_b = (
                [
                    cb_min + i * (cb_max - cb_min) / len(cb_bins)
                    for i in range(len(cb_bins) + 1)
                ]
                if cb_max > cb_min
                else [cb_min, cb_max]
            )

            def eval_cdf(edges: list[float], counts: list[int], x: float) -> float:
                if len(edges) < 2 or sum(counts) == 0:
                    return 0.0
                if x <= edges[0]:
                    return 0.0
                if x >= edges[-1]:
                    return 1.0
                total = sum(counts)
                # Find interval
                for j in range(len(counts)):
                    if edges[j] <= x <= edges[j + 1]:
                        base_prob = sum(counts[:j]) / total
                        bin_width = edges[j + 1] - edges[j]
                        fraction = (x - edges[j]) / bin_width if bin_width > 0 else 0.0
                        return base_prob + (counts[j] / total) * fraction
                return 1.0

            # 1. Shared-Grid PSI (10 bins spanning [global_min, global_max])
            n_shared_bins = 10
            shared_step = (
                (global_max - global_min) / n_shared_bins
                if global_max > global_min
                else 1.0
            )
            shared_grid = [
                global_min + i * shared_step for i in range(n_shared_bins + 1)
            ]

            eps = 0.0001
            for k in range(n_shared_bins):
                g_low = shared_grid[k]
                g_high = shared_grid[k + 1]
                prob_a = max(
                    0.0,
                    eval_cdf(edges_a, ca_bins, g_high)
                    - eval_cdf(edges_a, ca_bins, g_low),
                )
                prob_b = max(
                    0.0,
                    eval_cdf(edges_b, cb_bins, g_high)
                    - eval_cdf(edges_b, cb_bins, g_low),
                )

                pa = max(prob_a, eps)
                pb = max(prob_b, eps)
                psi += (pb - pa) * math.log(pb / pa)

            # 2. KS Statistic
            eval_points = sorted(set(edges_a + edges_b + shared_grid))
            max_diff = 0.0
            for pt in eval_points:
                diff = abs(
                    eval_cdf(edges_a, ca_bins, pt) - eval_cdf(edges_b, cb_bins, pt)
                )
                if diff > max_diff:
                    max_diff = diff
            ks_stat = float(max_diff)

            # 3. Wasserstein Distance
            if _SCIPY_AVAILABLE and len(ca_bins) > 0 and len(cb_bins) > 0:
                centers_a = [
                    0.5 * (edges_a[i] + edges_a[i + 1]) for i in range(len(ca_bins))
                ]
                centers_b = [
                    0.5 * (edges_b[i] + edges_b[i + 1]) for i in range(len(cb_bins))
                ]
                wd = float(
                    wasserstein_distance(
                        centers_a, centers_b, u_weights=ca_bins, v_weights=cb_bins
                    )
                )
            else:
                # Riemann numerical integration of |F_A(x) - F_B(x)| dx
                integral = 0.0
                for i in range(len(eval_points) - 1):
                    x_mid = 0.5 * (eval_points[i] + eval_points[i + 1])
                    dx = eval_points[i + 1] - eval_points[i]
                    integral += (
                        abs(
                            eval_cdf(edges_a, ca_bins, x_mid)
                            - eval_cdf(edges_b, cb_bins, x_mid)
                        )
                        * dx
                    )
                wd = float(integral)

        # Update shift determination using scientific metrics
        # PSI > 0.2 indicates significant population change
        if psi > 0.2 or ks_stat > 0.1:
            is_shift = True
            is_stable = False

        results.append(
            {
                "col_name": name,
                "mean_a": mean_a,
                "mean_b": mean_b,
                "shift_pct": shift_pct,
                "shift_abs": shift_abs,
                "is_stable": is_stable,
                "is_shift": is_shift,
                "psi": psi,
                "ks_stat": ks_stat,
                "wasserstein": wd,
                "status": drift_status,
                "uncertainty": uncertainty,
                "sample_size_a": sample_size_a,
                "sample_size_b": sample_size_b,
                "reason": drift_reason,
            }
        )

    return results


def compute_category_diff(
    cols_a: list,
    cols_b: list,
) -> list[dict]:
    """Compute category differences between datasets using single-pass C++ distinct_values.

    Eliminates full-file pandas reads while providing exact new/missing category tracking.
    """
    names_a = {c.name: c for c in cols_a}
    names_b = {c.name: c for c in cols_b}
    common = sorted(set(names_a.keys()) & set(names_b.keys()))

    results = []
    for name in common:
        ca = names_a[name]
        cb = names_b[name]
        if ca.type_str in ("int", "float", "bool") or cb.type_str in (
            "int",
            "float",
            "bool",
        ):
            continue

        distinct_a = list(getattr(ca, "distinct_values", []))
        distinct_b = list(getattr(cb, "distinct_values", []))
        set_a = set(distinct_a)
        set_b = set(distinct_b)
        overflow_a = getattr(ca, "distinct_overflowed", False)
        overflow_b = getattr(cb, "distinct_overflowed", False)
        overflowed = overflow_a or overflow_b

        total_a = getattr(ca, "total_count", 0)
        total_b = getattr(cb, "total_count", 0)

        # Case 1: Overflowed distinct values (>64 categories in C++ kernel)
        if overflowed:
            diff_approx = (getattr(cb, "unique_approx", 0) or 0) - (
                getattr(ca, "unique_approx", 0) or 0
            )
            results.append(
                {
                    "col_name": name,
                    "unique_a": getattr(ca, "unique_approx", None),
                    "unique_b": getattr(cb, "unique_approx", None),
                    "new_in_b": [],
                    "missing_in_b": [],
                    "diff_approx": diff_approx,
                    "jaccard": None,
                    "overflowed": True,
                    "status": "INDETERMINATE",
                    "reason": "Distinct values overflowed (>64 categories); exact category membership diff unavailable",
                }
            )
        # Case 2: Complete non-empty categorical evidence
        elif set_a or set_b:
            new_in_b = sorted(set_b - set_a)
            missing_in_b = sorted(set_a - set_b)
            overlap = set_a & set_b
            union = set_a | set_b
            jaccard = len(overlap) / len(union) if union else 1.0
            results.append(
                {
                    "col_name": name,
                    "unique_a": len(set_a),
                    "unique_b": len(set_b),
                    "new_in_b": new_in_b,
                    "missing_in_b": missing_in_b,
                    "jaccard": jaccard,
                    "overflowed": False,
                    "status": "EXACT",
                }
            )
        # Case 3: Both set_a and set_b are empty
        else:
            # Genuinely empty dataset (0 rows)
            if total_a == 0 and total_b == 0:
                results.append(
                    {
                        "col_name": name,
                        "unique_a": 0,
                        "unique_b": 0,
                        "new_in_b": [],
                        "missing_in_b": [],
                        "jaccard": 1.0,
                        "overflowed": False,
                        "status": "EXACT",
                    }
                )
            else:
                # Incomplete evidence (total rows > 0 but distinct_values empty)
                diff_approx = (getattr(cb, "unique_approx", 0) or 0) - (
                    getattr(ca, "unique_approx", 0) or 0
                )
                results.append(
                    {
                        "col_name": name,
                        "unique_a": getattr(ca, "unique_approx", None),
                        "unique_b": getattr(cb, "unique_approx", None),
                        "new_in_b": [],
                        "missing_in_b": [],
                        "diff_approx": diff_approx,
                        "jaccard": None,
                        "overflowed": False,
                        "status": "INDETERMINATE",
                        "reason": "Categorical distinct values unavailable in profile; category drift indeterminate",
                    }
                )

    return results


def compute_verdict(
    schema_diff: dict,
    shifts: list,
    category_diffs: list | None = None,
) -> dict:
    """Compute the overall comparison verdict.

    Returns a dict with:
        verdict: "PASS" | "REVIEW" | "FAIL"
        critical_errors: int
        warnings: int
        safe_to_train: bool
        message: str — human-readable summary
    """
    critical_errors = 0
    warnings = 0

    # Missing columns = critical (unless it's a binary target)
    for col in schema_diff["missing_in_b"]:
        if not looks_like_target_column(col):
            critical_errors += 1
        else:
            warnings += 1

    # Type mismatches = critical
    critical_errors += len(schema_diff["type_mismatches"])

    # Distribution shifts = warning
    for s in shifts:
        if s["is_shift"]:
            warnings += 1

    # Category drift / unseen categories in test set = warning
    if category_diffs:
        for c in category_diffs:
            if not c.get("overflowed") and c.get("new_in_b"):
                warnings += 1

    if critical_errors > 0:
        verdict = "FAIL"
        safe_to_train = False
    elif warnings > 0:
        verdict = "REVIEW"
        safe_to_train = True  # review but probably OK
    else:
        verdict = "PASS"
        safe_to_train = True

    parts = []
    if critical_errors:
        parts.append(
            f"{critical_errors} critical issue{'s' if critical_errors != 1 else ''}"
        )
    if warnings:
        parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
    if not parts:
        parts.append("no issues")

    message = f"{verdict} — {', '.join(parts)}"

    return {
        "verdict": verdict,
        "critical_errors": critical_errors,
        "warnings": warnings,
        "safe_to_train": safe_to_train,
        "message": message,
    }


def looks_like_target_column(col_name: str) -> bool:
    """Check if a column name looks like a binary ML target.

    Used to downgrade 'missing in test' from critical to warning when
    the missing column is the target (expected in ML train/test splits).
    """
    name_lower = col_name.lower()
    target_names = {
        "survived",
        "target",
        "label",
        "y",
        "class",
        "outcome",
        "is_",
        "has_",
    }
    return any(name_lower == t or name_lower.startswith(t) for t in target_names)


def compare(
    path_a: Any,
    path_b: Any,
    sample_size: int | None = None,
    correlate: bool = False,
) -> None:
    """
    Compare two datasets side by side for drift detection.

    Shows schema differences, null rate changes, distribution
    shifts, new categories, and a final verdict.
    """
    from ._engine import scan
    from ._errors import ZeddaError
    from ._format import safe_symbol, section_header, format_num

    try:
        from rich.console import Console
        from rich.markup import escape as rich_escape

        _console_default = Console()
        _rich_default = True
    except ImportError:
        _console_default = None
        _rich_default = False

    import sys

    zd_mod = sys.modules.get("zedda")
    rich_avail = (
        getattr(zd_mod, "_RICH_AVAILABLE", _rich_default)
        if zd_mod is not None
        else _rich_default
    )
    console_obj = (
        getattr(zd_mod, "_console", _console_default)
        if zd_mod is not None
        else _console_default
    )

    if not rich_avail or console_obj is None:
        raise ZeddaError(
            "Rich is required for terminal output. Install with: pip install rich"
        )
    _console = console_obj

    p_a = scan(path_a, sample_size=sample_size, correlate=correlate)
    p_b = scan(path_b, sample_size=sample_size, correlate=correlate)

    name_a = getattr(p_a, "file_name", str(path_a))
    name_b = getattr(p_b, "file_name", str(path_b))

    crit_sym = safe_symbol("✗", "[X]")
    warn_sym = safe_symbol("⚠", "[!]")
    check_sym = safe_symbol("✓", "[OK]")
    arrow_r = safe_symbol("→", "->")

    # Header
    _console.print(
        "\n[bold blue]zedda[/bold blue] [dim]v0.4.8[/dim]  [dim]·  compare mode[/dim]\n"
    )
    _console.print(
        f"  [bold]A[/bold] : [cyan]{name_a}[/cyan]"
        f"     [dim]{p_a.num_rows:,} rows  ·  {p_a.num_cols} cols[/dim]"
    )
    _console.print(
        f"  [bold]B[/bold] : [cyan]{name_b}[/cyan]"
        f"     [dim]{p_b.num_rows:,} rows  ·  {p_b.num_cols} cols[/dim]"
    )

    cols_a = {c.name: c for c in p_a.columns}
    cols_b = {c.name: c for c in p_b.columns}
    all_cols = list(dict.fromkeys(list(cols_a) + list(cols_b)))

    critical_errors = 0
    warnings_count = 0

    # Section 1: Schema
    _console.print(f"\n{section_header('Schema')}")

    if p_a.num_cols == p_b.num_cols:
        _console.print(
            f"  [green]{check_sym}[/green]  Column count   : "
            f"{p_a.num_cols} / {p_b.num_cols} match"
        )
    else:
        diff = abs(p_a.num_cols - p_b.num_cols)
        _console.print(
            f"  [yellow]{warn_sym}[/yellow]  Column count   : "
            f"{p_a.num_cols} vs {p_b.num_cols}  "
            f"[yellow]MISMATCH[/yellow] [dim](±{diff} col{'s' if diff != 1 else ''} — "
            f"expected if target/label column is absent in B)[/dim]"
        )
        warnings_count += 1

    type_match_count = 0
    type_total = 0
    for name in all_cols:
        ca = cols_a.get(name)
        cb = cols_b.get(name)

        if not cb:
            _console.print(
                f"  [yellow]{warn_sym}[/yellow]  {rich_escape(name):<16}: "
                f"[yellow]MISSING in {name_b}[/yellow]"
                f"  [dim](expected if this is the target/label column)[/dim]"
            )
            warnings_count += 1
        elif not ca:
            _console.print(
                f"  [yellow]{warn_sym}[/yellow]  {rich_escape(name):<16}: "
                f"[yellow]MISSING in {name_a}[/yellow]"
                f"  [dim](new column in {name_b})[/dim]"
            )
            warnings_count += 1
        else:
            type_total += 1
            if ca.type_str != cb.type_str:
                _console.print(
                    f"  [red]{crit_sym}[/red]  {rich_escape(name):<16}: "
                    f"{name_a}={ca.type_str}  {name_b}={cb.type_str}   "
                    f"[red]TYPE MISMATCH[/red]"
                )
                critical_errors += 1
            else:
                type_match_count += 1

    if type_total > 0:
        _console.print(
            f"  [green]{check_sym}[/green]  Types          : "
            f"{type_match_count} / {type_total} match"
        )

    # Section 2: Null Rates
    _console.print(f"\n{section_header('Null Rates')}")

    for name in all_cols:
        ca = cols_a.get(name)
        cb = cols_b.get(name)
        if not ca or not cb:
            continue

        delta = cb.null_pct - ca.null_pct
        if delta > 5:
            _console.print(
                f"  [yellow]{warn_sym}[/yellow]  {rich_escape(name):<16}: "
                f"{ca.null_pct:.1f}%  {arrow_r}  {cb.null_pct:.1f}%   "
                f"[yellow]SPIKE (+{delta:.1f}%)[/yellow]"
            )
            warnings_count += 1
        elif delta > 0.1:
            _console.print(
                f"  [yellow]{warn_sym}[/yellow]  {rich_escape(name):<16}: "
                f"{ca.null_pct:.1f}%  {arrow_r}  {cb.null_pct:.1f}%   "
                f"[dim](+{delta:.1f}%) minor increase[/dim]"
            )
        elif delta < -0.1:
            _console.print(
                f"  [green]{check_sym}[/green]  {rich_escape(name):<16}: "
                f"{ca.null_pct:.1f}%  {arrow_r}  {cb.null_pct:.1f}%   "
                f"[dim]({delta:.1f}%) minor decrease[/dim]"
            )
        else:
            _console.print(
                f"  [green]{check_sym}[/green]  {rich_escape(name):<16}: "
                f"{ca.null_pct:.1f}%  {arrow_r}  {cb.null_pct:.1f}%    "
                f"[dim]stable[/dim]"
            )

    # Section 3: Distribution Shift
    _console.print(f"\n{section_header('Distribution Shift')}")

    shifts = compute_distribution_shift(p_a.columns, p_b.columns)
    for s in shifts:
        name = s["col_name"]
        is_int = next(c.type_str == "int" for c in p_a.columns if c.name == name)
        mean_a_s = format_num(s["mean_a"], is_int)
        mean_b_s = format_num(s["mean_b"], is_int)
        shift_pct = s["shift_pct"]
        psi = s.get("psi", 0.0)
        ks_stat = s.get("ks_stat", 0.0)
        wd = s.get("wasserstein", 0.0)

        metrics_parts = []
        if abs(shift_pct) >= 1.0:
            metrics_parts.append(f"mean: {shift_pct:+.1f}%")
        if psi > 0.01:
            metrics_parts.append(f"PSI: {psi:.3f}")
        if ks_stat > 0.01:
            metrics_parts.append(f"KS: {ks_stat:.3f}")
        if wd > 0.01:
            metrics_parts.append(f"WD: {wd:.2f}")

        metrics_str = f"({', '.join(metrics_parts)})" if metrics_parts else ""

        if not s["is_stable"] and s["is_shift"]:
            _console.print(
                f"  [red]{crit_sym}[/red]  {rich_escape(name):<16}: "
                f"mean {mean_a_s} {arrow_r} {mean_b_s}  "
                f"[red]DRIFT {metrics_str}[/red]"
            )
            critical_errors += 1
        elif not s["is_stable"]:
            _console.print(
                f"  [yellow]{warn_sym}[/yellow]  {rich_escape(name):<16}: "
                f"mean {mean_a_s} {arrow_r} {mean_b_s}  "
                f"[yellow]SHIFT {metrics_str}[/yellow]"
            )
            warnings_count += 1
        else:
            _console.print(
                f"  [green]{check_sym}[/green]  {rich_escape(name):<16}: "
                f"mean {mean_a_s} {arrow_r} {mean_b_s}   "
                f"[dim]stable {metrics_str}[/dim]"
            )

    # Section 4: Category Drift
    cat_diffs = compute_category_diff(p_a.columns, p_b.columns)
    if cat_diffs:
        _console.print(f"\n{section_header('Category Drift')}")
        for c in cat_diffs:
            name = c["col_name"]
            if not c.get("overflowed"):
                new_b = c.get("new_in_b", [])
                missing_b = c.get("missing_in_b", [])
                jaccard = c.get("jaccard", 1.0)
                if new_b:
                    new_sample = ", ".join(f"'{v}'" for v in new_b[:3])
                    if len(new_b) > 3:
                        new_sample += f" (+{len(new_b) - 3} more)"
                    _console.print(
                        f"  [yellow]{warn_sym}[/yellow]  {rich_escape(name):<16}: "
                        f"[yellow]{len(new_b)} unseen value{'s' if len(new_b) != 1 else ''} in B[/yellow] "
                        f"({new_sample})  [dim]Jaccard={jaccard:.2f}[/dim]"
                    )
                    warnings_count += 1
                elif missing_b:
                    _console.print(
                        f"  [green]{check_sym}[/green]  {rich_escape(name):<16}: "
                        f"[dim]subset of A ({c['unique_b']}/{c['unique_a']} categories, no unseen values)[/dim]"
                    )
                else:
                    _console.print(
                        f"  [green]{check_sym}[/green]  {rich_escape(name):<16}: "
                        f"[dim]category sets match exactly ({c['unique_a']} unique)[/dim]"
                    )
            else:
                diff_approx = c.get("diff_approx", 0)
                if diff_approx > 0:
                    _console.print(
                        f"  [yellow]{warn_sym}[/yellow]  {rich_escape(name):<16}: "
                        f"[dim]high cardinality (~{c['unique_a']} in A vs ~{c['unique_b']} in B)[/dim]"
                    )
                else:
                    _console.print(
                        f"  [green]{check_sym}[/green]  {rich_escape(name):<16}: "
                        f"[dim]cardinality stable (~{c['unique_a']} unique)[/dim]"
                    )

    # Section 5: Verdict
    _console.print(f"\n{section_header('Verdict')}")

    if critical_errors > 0:
        _console.print(
            f"  [bold red]{crit_sym}  FAIL[/bold red]  —  "
            f"{critical_errors} critical error{'s' if critical_errors != 1 else ''}"
            + (
                f" · {warnings_count} warning{'s' if warnings_count != 1 else ''}"
                if warnings_count > 0
                else ""
            )
        )
        _console.print("  Safe to train : [bold red]NO[/bold red]")
    elif warnings_count > 0:
        _console.print(
            f"  [bold yellow]{warn_sym}  WARN[/bold yellow]  —  "
            f"{warnings_count} warning{'s' if warnings_count != 1 else ''}"
        )
        _console.print(
            "  Safe to train : [bold yellow]REVIEW[/bold yellow]"
            "  [dim]— check flagged shifts before proceeding[/dim]"
        )
    else:
        _console.print(
            f"  [bold green]{check_sym}  PASS[/bold green]  —  no issues found"
        )
        _console.print("  Safe to train : [bold green]YES[/bold green]")

    _console.print()
