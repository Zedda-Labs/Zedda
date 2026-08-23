"""
zedda._clean — canonical dataset cleaning orchestration.

Phase 5.8: Migrated from __init__.py to this canonical module.
Contains the complete clean() public API (presentation + logic).
Helper sub-functions (create_backup, apply_cleaning_fixes,
write_audit_trail, undo_clean) remain here alongside.

Public API: clean(), _clean_undo()
Internal helpers: create_backup, apply_cleaning_fixes, write_audit_trail
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from ._models import Change, CleaningPlan


def generate_plan(p: Any) -> CleaningPlan:
    """Generate a pure, immutable CleaningPlan from a DatasetProfile without side-effects.

    Each proposed Change explicitly cites the concrete Metric justification from the profile.
    """
    from ._warnings import is_outlier_column

    changes: list[Change] = []
    for col in getattr(p, "columns", []):
        col_name = getattr(col, "name", "<col>")
        null_pct = getattr(col, "null_pct", 0.0)
        type_str = getattr(col, "type_str", "unknown")
        unique_pct = getattr(col, "unique_pct", 0.0)
        unique_approx = getattr(col, "unique_approx", 0.0)
        is_constant = getattr(col, "is_constant", False)

        # High nulls -> drop
        if null_pct > 50 and type_str in ("str", "unknown"):
            changes.append(
                Change(
                    column=col_name,
                    operation="drop",
                    rationale=f"High null rate: {null_pct:.1f}% > 50%",
                    reversible=False,
                )
            )
            continue

        # Moderate nulls -> impute
        if null_pct > 1:
            method_desc = (
                "median for numeric"
                if type_str in ("int", "float")
                else "mode for categorical"
            )
            changes.append(
                Change(
                    column=col_name,
                    operation="impute",
                    rationale=f"Null rate: {null_pct:.1f}% > 1% ({method_desc})",
                    reversible=True,
                )
            )

        # ID-like integer -> drop
        if type_str == "int" and unique_pct > 95:
            changes.append(
                Change(
                    column=col_name,
                    operation="drop",
                    rationale=f"ID-like integer column: {unique_pct:.1f}% unique > 95%",
                    reversible=False,
                )
            )
            continue

        # High cardinality string -> encode
        if type_str in ("str", "unknown") and unique_approx > 50:
            changes.append(
                Change(
                    column=col_name,
                    operation="encode",
                    rationale=f"High cardinality string: approx {unique_approx} distinct values > 50",
                    reversible=True,
                )
            )
            continue

        # Constant column -> drop
        if is_constant:
            changes.append(
                Change(
                    column=col_name,
                    operation="drop",
                    rationale="Constant column: 1 unique value across dataset",
                    reversible=False,
                )
            )
            continue

        # Outlier -> clip
        if is_outlier_column(col):
            val_max = getattr(col, "val_max", 0.0)
            mean_val = getattr(col, "mean", 0.0)
            changes.append(
                Change(
                    column=col_name,
                    operation="clip",
                    rationale=f"Extreme outlier: max {val_max} > 10x mean {mean_val}",
                    reversible=True,
                )
            )

    return CleaningPlan(
        proposed_changes=changes,
        generated_from=getattr(p, "file_name", "<profile>"),
        requires_approval=True,
        dry_run=True,
    )


def create_backup(path: str) -> str | None:
    """Create a backup of the file if it doesn't already exist.

    FIX P-H9: Backup path is {path}.zedda-backup. Only creates a backup
    if one doesn't already exist (idempotent — never overwrites the
    original backup).

    Returns the backup path, or None if no backup was created (e.g.,
    input is a temp file).
    """
    backup_path = str(path) + ".zedda-backup"
    if not Path(backup_path).exists():
        shutil.copy2(path, backup_path)
        return backup_path
    return None  # backup already exists — don't overwrite


def apply_cleaning_fixes(df: Any, p: Any, original_cols: int) -> tuple:
    """Apply all auto-fixable warnings to a DataFrame.

    Returns (cleaned_df, audit_actions, dropped_cols) where:
        cleaned_df: the modified DataFrame
        audit_actions: list of dicts describing each action taken
        dropped_cols: list of column names that were dropped
    """
    import pandas as pd

    audit_actions = []
    dropped_cols = []
    cols_before = len(df.columns)

    for col in p.columns:
        col_name = col.name
        if col_name not in df.columns:
            continue

        col_data = df[col_name]
        null_count = int(col_data.isnull().sum())

        # High nulls → drop
        if col.null_pct > 50 and col.type_str in ("str", "unknown"):
            df = df.drop(columns=[col_name], errors="ignore")
            dropped_cols.append(col_name)
            audit_actions.append(
                {
                    "column": col_name,
                    "action": "drop",
                    "reason": f"{col.null_pct:.1f}% nulls — too sparse",
                }
            )
            continue

        # Moderate nulls → impute
        if null_count > 0 and col.null_pct > 1:
            if col.type_str in ("int", "float"):
                coerced = pd.to_numeric(col_data, errors="coerce")
                coerced_count = max(0, int(coerced.isnull().sum() - null_count))
                fill_val = coerced.median()
                df[col_name] = coerced.fillna(fill_val)
                audit_actions.append(
                    {
                        "column": col_name,
                        "action": "impute",
                        "fill_value": str(fill_val),
                        "cells_fixed": null_count + coerced_count,
                    }
                )
            else:
                # FIX P-M29: Cache mode() result
                m = col_data.mode()
                fill_val = m[0] if not m.empty else "Unknown"
                df[col_name] = col_data.fillna(fill_val)
                audit_actions.append(
                    {
                        "column": col_name,
                        "action": "impute",
                        "fill_value": str(fill_val),
                        "cells_fixed": null_count,
                    }
                )

        # ID-like integer → drop
        if col.type_str == "int" and col.unique_pct > 95:
            df = df.drop(columns=[col_name], errors="ignore")
            dropped_cols.append(col_name)
            audit_actions.append(
                {
                    "column": col_name,
                    "action": "drop",
                    "reason": "ID-like column (unique_pct > 95%)",
                }
            )
            continue

        # High cardinality string → label encode
        if col.type_str in ("str", "unknown") and col.unique_approx > 50:
            df[col_name] = pd.Categorical(df[col_name]).codes
            audit_actions.append(
                {
                    "column": col_name,
                    "action": "encode",
                    "reason": f"{col.unique_approx} unique values — label encoded",
                }
            )
            continue

        # Constant → drop
        if col.is_constant:
            df = df.drop(columns=[col_name], errors="ignore")
            dropped_cols.append(col_name)
            audit_actions.append(
                {
                    "column": col_name,
                    "action": "drop",
                    "reason": "constant value",
                }
            )
            continue

        # Outlier → clip
        from ._warnings import is_outlier_column

        if is_outlier_column(col):
            upper = pd.to_numeric(df[col_name], errors="coerce").quantile(0.99)
            if pd.notna(upper):
                before_max = pd.to_numeric(df[col_name], errors="coerce").max()
                df[col_name] = (
                    pd.to_numeric(df[col_name], errors="coerce")
                    .clip(upper=upper)
                    .infer_objects(copy=False)
                )
                clipped = int(
                    (pd.to_numeric(df[col_name], errors="coerce") != before_max).sum()
                )
                audit_actions.append(
                    {
                        "column": col_name,
                        "action": "clip",
                        "upper_bound": float(upper),
                        "cells_clipped": clipped,
                    }
                )

    return df, audit_actions, dropped_cols


def write_audit_trail(
    audit_path: str,
    source_file: str,
    output_file: str,
    version: str,
    score_before: int,
    score_after: int,
    rows_before: int,
    rows_after: int,
    cols_before: int,
    cols_after: int,
    actions: list,
) -> None:
    """Write the JSON audit trail for a cleaning operation.

    FIX P-H10: Verifies the audit path is in the same directory as the
    output file (prevents path traversal via user-supplied output paths).
    """
    # Verify audit path is in the same directory as output
    if Path(audit_path).resolve().parent != Path(output_file).resolve().parent:
        raise ValueError("Audit path traversal detected — refusing to write.")

    audit_data = {
        "source_file": source_file,
        "output_file": Path(output_file).name,
        "zedda_version": version,
        "score_before": score_before,
        "score_after": score_after,
        "rows_before": rows_before,
        "rows_after": rows_after,
        "cols_before": cols_before,
        "cols_after": cols_after,
        "actions": actions,
    }
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=2, ensure_ascii=False)


def undo_clean(path: str) -> None:
    """Restore a file from its zedda backup."""
    backup = str(path) + ".zedda-backup"
    if not Path(backup).exists():
        from ._errors import ZeddaError

        raise ZeddaError(
            f"No backup found: '{backup}'\n"
            "Tip: zd.clean() creates a backup before modifying files."
        )
    shutil.copy2(backup, str(path))


# ─────────────────────────────────────────────────────────────────
#  clean() — canonical public API
#  Phase 5.8: Migrated from __init__.py into this module.
#  Orchestrates: scan → collect warnings → backup → apply fixes →
#  rescan → score → write audit trail → Rich output.
# ─────────────────────────────────────────────────────────────────
def clean(
    path: Any,
    output: str | None = None,
    sample_size: int | None = None,
    dry_run: bool = False,
    approved: bool = True,
) -> Any:
    """
    Auto-clean a dataset by applying all auto-fixable warnings.

    Creates a backup, applies fixes (impute, drop, encode), and
    saves the cleaned file with a JSON audit trail and rollback manifest.

    Args:
        path (str): Path to a ``.csv``, ``.parquet``, or ``.arrow`` file.
        output (str, optional): Output file path. If None, overwrites
            the original (after creating a backup).
        sample_size (int, optional): Max rows to sample for profiling.
        dry_run (bool, optional): If True, returns a CleaningPlan without modifying files.
        approved (bool, optional): Approval flag for execution (default: True).

    Returns:
        pandas.DataFrame | CleaningPlan: The cleaned DataFrame or CleaningPlan (if dry_run=True).

    Example::

        import zedda as zd
        plan = zd.clean("titanic.csv", dry_run=True)
        zd.clean("titanic.csv", output="titanic_clean.csv")
        zd.clean.undo("titanic.csv")  # restore from backup
    """
    from ._errors import ZeddaError
    from ._clean_executor import execute_cleaning_transaction

    # ── Rich resolution (matches _warnings.py / _merge.py pattern) ──
    try:
        from rich.console import Console
        from rich.markup import escape as rich_escape

        _console_default = Console()
        _rich_default = True
    except ImportError:
        _console_default = None
        _rich_default = False
        rich_escape = str  # type: ignore[assignment]

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

    # ── Resolve dependencies from zedda module ───────────────────────
    version = getattr(zd_mod, "__version__", "0.4.8") if zd_mod is not None else "0.4.8"

    from ._engine import scan as _scan_wrapper
    from ._warnings import collect_warnings as _collect_warnings
    from ._profile_print import _quality_score, _render_quality_bar, _quality_label
    from ._format import safe_symbol as _safe_symbol
    from ._resolve import resolve_input as _resolve_input, cleanup_temp as _cleanup_temp

    def _require_pyarrow():
        try:
            import pyarrow  # noqa: F401
            import pyarrow.parquet  # noqa: F401
        except ImportError as e:
            from ._errors import ZeddaError

            raise ZeddaError(
                "Parquet/Arrow support requires pyarrow, which is not "
                "installed. Install it with: pip install zedda[parquet]"
            ) from e

    resolved_path, is_in_memory = _resolve_input(path)

    try:
        import pandas as pd
    except ImportError:
        raise ZeddaError("pandas is required for clean(). Run: pip install pandas")

    try:
        file_name = (
            "<DataFrame>"
            if is_in_memory
            else (Path(path).name if isinstance(path, (str, Path)) else "<DataFrame>")
        )

        crit_sym = _safe_symbol("✗", "[X]")
        warn_sym = _safe_symbol("⚠", "[!]")
        check_sym = _safe_symbol("✓", "[OK]")
        arrow_r = _safe_symbol("→", "->")
        bullet = _safe_symbol("·", "-")

        # ── Profile BEFORE ──────────────────────────────────────────
        p = _scan_wrapper(resolved_path, sample_size=sample_size)
        plan = generate_plan(p)

        # If dry_run, return pure CleaningPlan without mutation or heavy printing
        if dry_run:
            return plan

        # ── Header ──────────────────────────────────────────────────
        _console.print(
            f"\n[bold blue]zedda[/bold blue] [dim]v{version}[/dim]  {bullet}  "
            f"[bold]clean mode[/bold]\n"
        )

        all_warnings = _collect_warnings(p)
        fixable = [w for w in all_warnings if w.get("auto_fixable")]

        score_before = _quality_score(p)
        n_critical = sum(1 for w in all_warnings if w["severity"] == "critical")
        n_warning = sum(1 for w in all_warnings if w["severity"] == "warning")
        n_info = sum(1 for w in all_warnings if w["severity"] == "info")

        bar = _render_quality_bar(score_before)
        color, label = _quality_label(score_before)

        _console.print("[bold]Before[/bold]")
        _console.print(
            f"  Quality score : [{color}]{score_before}/100  {bar}  {label}[/{color}]"
        )
        _console.print(
            f"  Issues found  : {len(all_warnings)}  "
            f"({n_critical} critical {bullet} {n_warning} warning{'s' if n_warning != 1 else ''}"
            f" {bullet} {n_info} info)\n"
        )

        if not fixable:
            _console.print(
                f"  [green]{check_sym}  No auto-fixable issues — data is already clean![/green]\n"
            )
            return None

        # ── Load the data ───────────────────────────────────────────
        if is_in_memory:
            if "polars" in getattr(type(path), "__module__", ""):
                df = path.to_pandas()
            else:
                df = path.copy()
        else:
            assert isinstance(resolved_path, str)
            ext = Path(resolved_path).suffix.lower()
            if ext == ".csv":
                df = pd.read_csv(resolved_path)
            elif ext in (".parquet", ".arrow"):
                df = pd.read_parquet(resolved_path)
            else:
                raise ZeddaError(f"Unsupported format for clean: {ext}")

        rows_before = len(df)
        cols_before = len(df.columns)

        # ── Apply fixes ─────────────────────────────────────────────
        _console.print("[bold]Applying Fixes[/bold]")
        audit_actions = []
        dropped_cols = []

        for w in fixable:
            col_name = w["column"]
            action = w["action_type"]
            safe_display = rich_escape(col_name)

            if action == "drop":
                if col_name in df.columns:
                    reason = w["message"]
                    df = df.drop(columns=[col_name])
                    dropped_cols.append(col_name)
                    _console.print(
                        f"  [green]{check_sym}[/green]  {safe_display} {arrow_r} dropped ({reason})"
                        f"      [dim]col removed[/dim]"
                    )
                    audit_actions.append(
                        {
                            "column": col_name,
                            "action": "drop",
                            "reason": w["message"],
                        }
                    )

            elif action == "impute":
                if col_name in df.columns:
                    col_data = df[col_name]
                    col_obj = next((c for c in p.columns if c.name == col_name), None)
                    null_count = (
                        int(col_obj.null_count)
                        if col_obj
                        else int(col_data.isnull().sum())
                    )
                    if col_obj and col_obj.type_str in ("int", "float"):
                        coerced_data = pd.to_numeric(col_data, errors="coerce")
                        coerced_count = max(
                            0, int(coerced_data.isnull().sum() - null_count)
                        )

                        fill_val = coerced_data.median()
                        df[col_name] = coerced_data.fillna(fill_val)

                        _console.print(
                            f"  [green]{check_sym}[/green]  {safe_display}"
                            f" {arrow_r} median imputed ({fill_val:.2f})"
                            f"      [dim]{null_count + coerced_count} cells[/dim]"
                        )
                        if coerced_count > 0:
                            _console.print(
                                f"     [yellow]{warn_sym}[/yellow]  {safe_display} — {coerced_count} values could not be parsed as numbers and were treated as missing before imputation."
                            )
                    else:
                        m = col_data.mode()
                        fill_val = m[0] if not m.empty else "Unknown"
                        df[col_name] = col_data.fillna(fill_val)
                        _console.print(
                            f"  [green]{check_sym}[/green]  {safe_display}"
                            f" {arrow_r} mode imputed ({fill_val})"
                            f"      [dim]{null_count} cells[/dim]"
                        )
                    audit_actions.append(
                        {
                            "column": col_name,
                            "action": "impute",
                            "fill_value": str(fill_val),
                            "cells_fixed": null_count,
                        }
                    )

            elif action == "encode":
                if col_name in df.columns:
                    n_unique = df[col_name].nunique()
                    df[col_name] = pd.Categorical(df[col_name]).codes
                    _console.print(
                        f"  [green]{check_sym}[/green]  {safe_display}"
                        f" {arrow_r} label encoded ({n_unique} unique)"
                        f"      [dim]encoded[/dim]"
                    )
                    audit_actions.append(
                        {
                            "column": col_name,
                            "action": "encode",
                            "unique_values": n_unique,
                        }
                    )

            elif action == "clip":
                if col_name in df.columns:
                    upper = df[col_name].quantile(0.99)
                    clipped = int((df[col_name] > upper).sum())
                    df[col_name] = df[col_name].clip(upper=upper)
                    _console.print(
                        f"  [green]{check_sym}[/green]  {safe_display}"
                        f" {arrow_r} clipped at p99 ({upper:.2f})"
                        f"      [dim]{clipped} cells[/dim]"
                    )
                    audit_actions.append(
                        {
                            "column": col_name,
                            "action": "clip",
                            "upper_bound": float(upper),
                            "cells_clipped": clipped,
                        }
                    )

        # ── Compute AFTER score ─────────────────────────────────────
        tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        tmp.close()
        score_after: int | None = None
        try:
            _require_pyarrow()
            import pyarrow as pa
            import pyarrow.parquet as pq

            table = pa.Table.from_pandas(df, preserve_index=False)
            pq.write_table(table, tmp.name)
            p_after = _scan_wrapper(tmp.name)
            score_after = _quality_score(p_after, original_cols=cols_before)
        except Exception:
            pass
        finally:
            _cleanup_temp(tmp.name)

        if score_after is None:
            score_after = score_before

        improvement = score_after - score_before
        rows_after = len(df)
        cols_after = len(df.columns)

        bar_a = _render_quality_bar(score_after)
        color_a, label_a = _quality_label(score_after)

        _console.print("\n[bold]After[/bold]")
        sign = "+" if improvement >= 0 else ""
        color_imp = "green" if improvement >= 0 else "red"
        _console.print(
            f"  Quality score : [{color_a}]{score_after}/100  "
            f"{bar_a}  {label_a}[/{color_a}]"
            f"  [{color_imp}]({sign}{improvement} points)[/{color_imp}]"
        )
        n_dropped = len(dropped_cols)
        _console.print(
            f"  Rows : {rows_before:,} {arrow_r} {rows_after:,}   "
            f"Cols : {cols_before} {arrow_r} {cols_after}"
            + (f"  ({n_dropped} dropped)" if n_dropped > 0 else "")
        )

        # ── Transactional Save Output ───────────────────────────────
        t0 = time.perf_counter()
        target_path = None if (is_in_memory and not output) else (output if output else str(resolved_path))

        exec_record, out_path, backup_path, manifest_path = execute_cleaning_transaction(
            df=df,
            plan=plan,
            target_path=target_path,
            audit_actions=audit_actions,
            score_before=score_before,
            score_after=score_after,
            version=version,
            approved_by="user" if approved else "unapproved",
        )
        elapsed = (time.perf_counter() - t0) * 1000

        # Legacy audit trail file compatibility
        audit_path = None
        if out_path is not None:
            audit_path = str(Path(out_path).with_suffix("")) + ".audit.json"
            if Path(audit_path).resolve().parent != Path(out_path).resolve().parent:
                raise ZeddaError("Audit path traversal detected — refusing to write.")
            audit_data = {
                "source_file": file_name,
                "output_file": Path(out_path).name,
                "zedda_version": version,
                "score_before": score_before,
                "score_after": score_after,
                "rows_before": rows_before,
                "rows_after": rows_after,
                "cols_before": cols_before,
                "cols_after": cols_after,
                "actions": audit_actions,
            }
            with open(audit_path, "w", encoding="utf-8") as f:
                json.dump(audit_data, f, indent=2, ensure_ascii=False)

        _console.print("\n[bold]Output[/bold]")
        if out_path is not None:
            _console.print(
                f"  [green]{check_sym}[/green]  Clean file  {arrow_r} {Path(out_path).name}"
            )
            if audit_path:
                _console.print(
                    f"  [green]{check_sym}[/green]  Audit trail {arrow_r} {Path(audit_path).name}"
                )
            if manifest_path:
                _console.print(
                    f"  [green]{check_sym}[/green]  Rollback manifest {arrow_r} {Path(manifest_path).name}"
                )
            if backup_path:
                _console.print(
                    f"     Time: {elapsed:.1f}ms  {bullet}  Backup: {Path(backup_path).name}\n"
                )
            else:
                _console.print(f"     Time: {elapsed:.1f}ms\n")
        else:
            _console.print(
                f"  [green]{check_sym}[/green]  Returned cleaned DataFrame "
                "(no file written — input was a DataFrame and `output` was not set)."
            )
            if backup_path:
                _console.print(f"     Backup: {Path(backup_path).name}\n")
            else:
                _console.print()

        return df

    finally:
        if is_in_memory:
            _cleanup_temp(resolved_path)


def _clean_undo(path: Any) -> None:
    """Restore a file from its zedda backup (with Rich console output if available)."""
    from ._errors import ZeddaError

    check_sym_default = "[OK]"
    try:
        from rich.markup import escape as _re  # noqa: F401

        check_sym_default = "✓"
    except ImportError:
        pass

    zd_mod = sys.modules.get("zedda")
    rich_avail = (
        getattr(zd_mod, "_RICH_AVAILABLE", False) if zd_mod is not None else False
    )
    console_obj = getattr(zd_mod, "_console", None) if zd_mod is not None else None
    _safe_symbol = getattr(zd_mod, "_safe_symbol", None) if zd_mod is not None else None

    check_sym = _safe_symbol("✓", "[OK]") if _safe_symbol else check_sym_default

    backup = str(path) + ".zedda-backup"
    if not Path(backup).exists():
        raise ZeddaError(
            f"No backup found: '{backup}'\n"
            "Tip: zd.clean() creates a backup before modifying files."
        )
    shutil.copy2(backup, str(path))
    if rich_avail and console_obj is not None:
        console_obj.print(
            f"\n[green]{check_sym}[/green]  Restored [cyan]{Path(path).name}[/cyan] "
            f"from backup.\n"
        )
    else:
        print(f"Restored {path} from backup.")


clean.undo = _clean_undo  # type: ignore[attr-defined]
clean.generate_plan = generate_plan  # type: ignore[attr-defined]

