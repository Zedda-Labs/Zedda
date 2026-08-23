"""
zedda._merge — dataset merge logic.

FIX Batch 31 / P-M1: Extracted from __init__.py to reduce module size.
Contains the pure merge logic — no Rich console dependency.
The presentation layer (Rich rendering) stays in __init__.py.

Internal — not part of the public API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def compute_overlap_count(dataframes: list, common_cols: list) -> int:
    """Count duplicate rows across all DataFrames (based on common columns).

    FIX P-H7: Replaces the O(N²) pair-wise merge approach with a single
    O(N) pass: concat all DataFrames, then count duplicates.

    Returns the number of duplicate rows found.
    """
    if len(dataframes) < 2 or not common_cols:
        return 0
    import pandas as pd

    combined = pd.concat(dataframes, ignore_index=True)
    # Count duplicates (excluding the first occurrence)
    return int(combined.duplicated(subset=common_cols, keep="first").sum())


def compute_schema_mismatches(
    dataframes: list,
    file_names: list,
) -> list:
    """Check schema consistency across DataFrames.

    Returns a list of dicts, each with:
        file: str — file name with the mismatch
        missing: list of str — columns missing vs the reference (file 0)
        extra: list of str — extra columns vs the reference
    """
    if len(dataframes) < 2:
        return []

    ref_cols = set(dataframes[0].columns)
    mismatches = []
    for i, df in enumerate(dataframes[1:], 1):
        this_cols = set(df.columns)
        missing = sorted(ref_cols - this_cols)
        extra = sorted(this_cols - ref_cols)
        if missing or extra:
            mismatches.append(
                {
                    "file": file_names[i],
                    "missing": missing,
                    "extra": extra,
                }
            )
    return mismatches


def combine_dataframes(
    dataframes: list,
    common_cols: list,
    file_names: list,
) -> Any:
    """Combine DataFrames with dedup and source tracking.

    FIX P-H8: Dedup uses common_cols as subset (not ALL columns).
    Adds a 'zedda_source_file' column for tracking provenance.

    Returns the combined DataFrame.
    """
    import pandas as pd

    # Add source tracking column
    for df, name in zip(dataframes, file_names):
        df["zedda_source_file"] = name

    combined = pd.concat(dataframes, ignore_index=True)

    # Dedup on common columns (not ALL columns — FIX P-H8)
    if common_cols:
        before = len(combined)
        combined = combined.drop_duplicates(subset=common_cols, keep="first")
        deduped = before - len(combined)
    else:
        deduped = 0

    return combined, deduped


def merge(
    paths: list,
    output: str = "combined.csv",
    sample_size: int | None = None,
    policy: str = "union",
    dedup: bool = True,
    strict: bool = False,
) -> Any:
    """
    Merge multiple CSV/Parquet files with intelligent checks.

    Performs schema validation, duplicate detection, distribution
    shift analysis, and adds a source tracking column.

    Args:
        paths (list): List of file paths or DataFrames to merge.
        output (str): Output file path (default: "combined.csv").
        sample_size (int, optional): Max rows to sample per file.
        policy (str, optional): Schema reconciliation policy ("union", "intersection", "strict").
        dedup (bool, optional): Whether to remove duplicate rows across sources.
        strict (bool, optional): If True, fails on schema mismatches or unreadable inputs.

    Returns:
        pandas.DataFrame: The merged DataFrame.

    Example::

        import zedda as zd
        zd.merge(["jan.csv", "feb.csv", "mar.csv"], output="combined.csv")
    """
    from ._errors import ZeddaError

    if not isinstance(paths, (list, tuple)) or len(paths) < 2:
        raise ZeddaError("merge() requires a list of at least 2 file paths.")

    if policy not in ("union", "intersection", "strict"):
        raise ZeddaError(
            f"Invalid merge policy: '{policy}'. Expected 'union', 'intersection', or 'strict'."
        )

    from ._engine import scan
    from ._format import safe_symbol
    import time

    try:
        import pandas as pd
    except ImportError as e:
        raise ZeddaError(
            "pandas is required for merge(). Run: pip install pandas"
        ) from e

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

    n_files = len(paths)

    # ── Header ──────────────────────────────────────────────────
    _console.print(
        f"\n[bold blue]zedda[/bold blue] [dim]v0.4.8[/dim]  ·  "
        f"[bold]merge mode[/bold]  ·  [dim]{n_files} files[/dim]\n"
    )

    check_sym = safe_symbol("✓", "[OK]")
    crit_sym = safe_symbol("✗", "[X]")
    warn_sym = safe_symbol("⚠", "[!]")

    # ── Profile each file ───────────────────────────────────────
    profiles = []
    dataframes = []
    file_names = []

    for file_path in paths:
        try:
            try:
                p = scan(file_path, sample_size=sample_size)
            except Exception as e:
                name = (
                    Path(file_path).name
                    if isinstance(file_path, (str, Path))
                    else "<DataFrame>"
                )
                if strict:
                    raise ZeddaError(f"Failed to scan input '{name}': {e}") from e
                _console.print(
                    f"  [red]{crit_sym}[/red] {name}  [dim]skipped: {e}[/dim]"
                )
                continue

            profiles.append(p)
            name = (
                Path(file_path).name
                if isinstance(file_path, (str, Path))
                else "<DataFrame>"
            )
            file_names.append(name)

            if hasattr(file_path, "to_pandas"):
                df = file_path.to_pandas()
            elif hasattr(file_path, "copy") and not isinstance(file_path, (str, Path)):
                df = file_path.copy()
            else:
                resolved_str = str(file_path)
                ext = Path(resolved_str).suffix.lower()
                if ext == ".csv":
                    df = pd.read_csv(resolved_str)
                elif ext in (".parquet", ".arrow"):
                    df = pd.read_parquet(resolved_str)
                else:
                    raise ZeddaError(f"Unsupported format: {ext}")
            dataframes.append(df)

            _console.print(
                f"  [green]{check_sym}[/green] {name}  "
                f"[dim]{p.num_rows:,} rows · {p.num_cols} cols · "
                f"{p.overall_null_pct:.1f}% nulls[/dim]"
            )
        except ZeddaError:
            if strict:
                raise
            continue
        except Exception as e:
            if strict:
                name = (
                    Path(file_path).name
                    if isinstance(file_path, (str, Path))
                    else "<DataFrame>"
                )
                raise ZeddaError(f"Failed to load input '{name}': {e}") from e
            continue

    _console.print()

    if not dataframes:
        raise ZeddaError("All input files failed to load during merge().")

    # ── Schema Check ────────────────────────────────────────────
    _console.print("[bold]Schema Check[/bold]")
    ref_cols = set(dataframes[0].columns)
    ref_n = len(ref_cols)
    schema_ok = True

    for i, df in enumerate(dataframes[1:], 1):
        this_cols = set(df.columns)
        if this_cols != ref_cols:
            missing = ref_cols - this_cols
            extra = this_cols - ref_cols
            schema_ok = False
            if missing:
                _console.print(
                    f"  [red]{crit_sym}[/red]  {file_names[i]}: missing columns "
                    f"[red]{', '.join(missing)}[/red]"
                )
            if extra:
                _console.print(
                    f"  [yellow]{warn_sym}[/yellow]  {file_names[i]}: extra columns "
                    f"[yellow]{', '.join(extra)}[/yellow]"
                )

    if not schema_ok and policy == "strict":
        raise ZeddaError(
            "Schema mismatch across merged inputs in strict mode. "
            "Use policy='union' or policy='intersection' to reconcile."
        )

    if schema_ok:
        _console.print(
            f"  [green]{check_sym}[/green]  {ref_n}/{ref_n} columns match "
            f"across all {n_files} files"
        )
    _console.print()

    # ── Overlap / Duplicate Check ───────────────────────────────
    _console.print("[bold]Overlap Check[/bold]")
    total_dupes_removed = 0
    common_cols = list(ref_cols.intersection(*[set(df.columns) for df in dataframes]))

    for i in range(len(dataframes)):
        for j in range(i + 1, len(dataframes)):
            if not common_cols:
                break
            try:
                df_i_unique = dataframes[i][common_cols].drop_duplicates()
                df_j_unique = dataframes[j][common_cols].drop_duplicates()
                merged_check = pd.merge(
                    df_i_unique,
                    df_j_unique,
                    how="inner",
                )
                n_overlap = len(merged_check)
                if n_overlap > 0:
                    _console.print(
                        f"  [yellow]{warn_sym}[/yellow]  {n_overlap} duplicate rows found "
                        f"between {file_names[i]} and {file_names[j]}"
                    )
                    _console.print(
                        f"     [dim]Keeping first occurrence, removing from "
                        f"{file_names[j]}.[/dim]"
                    )
                    total_dupes_removed += n_overlap
            except Exception as e:
                _console.print(f"     [dim]Merge check failed: {e}[/dim]")

    if total_dupes_removed == 0:
        _console.print(f"  [green]{check_sym}[/green]  No duplicate rows found")
    _console.print()

    # ── Distribution Check ──────────────────────────────────────
    _console.print("[bold]Distribution Check[/bold]")
    has_shift = False
    if profiles:
        ref_profile = profiles[0]
        for col in ref_profile.columns:
            if col.type_str not in ("int", "float"):
                continue
            if (
                col.type_str == "int" and col.unique_pct > 95
            ) or col.unique_approx <= 2:
                continue
            for i, other_p in enumerate(profiles[1:], 1):
                other_col = next(
                    (c for c in other_p.columns if c.name == col.name), None
                )
                if other_col is None or other_col.type_str not in ("int", "float"):
                    continue
                if col.mean is not None and col.mean > 0 and other_col.mean is not None:
                    shift_pct = (other_col.mean - col.mean) / col.mean * 100
                    if abs(shift_pct) > 15:
                        has_shift = True
                        _console.print(
                            f"  [yellow]{warn_sym}[/yellow]  '{rich_escape(col.name)}' — "
                            f"{file_names[i]} is {shift_pct:+.0f}% "
                            f"{'above' if shift_pct > 0 else 'below'} "
                            f"{file_names[0]} mean, worth investigating"
                        )

    if not has_shift:
        _console.print(
            f"  [green]{check_sym}[/green]  No significant distribution shifts"
        )
    _console.print()

    # ── Merging ─────────────────────────────────────────────────
    _console.print("[bold]Merging[/bold]")
    t0 = time.perf_counter()

    # Apply schema policy
    if policy == "intersection" and common_cols:
        prepared_dfs = [
            df[common_cols].assign(zedda_source_file=file_names[i])
            for i, df in enumerate(dataframes)
        ]
    else:
        prepared_dfs = [
            df.assign(zedda_source_file=file_names[i])
            for i, df in enumerate(dataframes)
        ]

    combined = pd.concat(prepared_dfs, ignore_index=True)

    if dedup:
        cols_for_dedup = [c for c in combined.columns if c != "zedda_source_file"]
        before_dedup = len(combined)
        combined = combined.drop_duplicates(subset=cols_for_dedup, keep="first")
        actual_dupes = before_dedup - len(combined)
    else:
        actual_dupes = 0

    elapsed_ms = (time.perf_counter() - t0) * 1000

    _console.print(
        f"  [green]{check_sym}[/green]  {len(combined):,} rows combined"
        + (f" ({actual_dupes} duplicates removed)" if actual_dupes > 0 else "")
    )
    _console.print(
        f"  [green]{check_sym}[/green]  Source column added: 'zedda_source_file'"
    )
    _console.print()

    # ── Save output ─────────────────────────────────────────────
    if output:
        out_ext = Path(output).suffix.lower()
        if out_ext in (".parquet", ".arrow"):
            combined.to_parquet(output, index=False)
        else:
            combined.to_csv(output, index=False)

        _console.print("[bold]Output[/bold]")
        _console.print(
            f"  [green]{check_sym}[/green]  {Path(output).name} saved · "
            f"{len(combined):,} rows · {len(combined.columns)} cols · "
            f"{elapsed_ms:.0f} ms"
        )
        _console.print(
            f'\n  [dim]Run zd.profile("{Path(output).name}") '
            f"to profile the merged dataset.[/dim]\n"
        )

    return combined
