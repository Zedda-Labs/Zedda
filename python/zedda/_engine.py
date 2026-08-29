from __future__ import annotations

from typing import Any

from ._adapters.registry import AdapterRegistry
from ._compat import legacy_to_profile_result


def _scan_legacy(
    source: Any,
    sample_size: int | None = None,
    correlate: bool = False,
    allowed_dir: str | None = None,
    **kwargs,
) -> Any:
    """Internal scan that returns the C++ profile object and the adapter.

    Used by profile() and _print_report() to maintain legacy formatting.
    """
    from pathlib import Path

    from ._errors import ZeddaError

    try:
        if isinstance(source, (str, Path)):
            resolved = Path(source).resolve()
            if allowed_dir:
                allowed = Path(allowed_dir).resolve()
                try:
                    resolved.relative_to(allowed)
                except ValueError:
                    raise ZeddaError(
                        f"Path '{source}' resolves to '{resolved}' which is outside "
                        f"the allowed directory '{allowed}'."
                    )
            if (
                resolved.exists()
                and resolved.is_file()
                and resolved.stat().st_size == 0
            ):
                raise ZeddaError(
                    f"File is empty (0 bytes): '{source}'\n"
                    "Tip: Check that the file was written correctly."
                )

        adapter = AdapterRegistry.resolve(
            source,
            is_sampled=(sample_size is not None),
            sample_size=sample_size or 1_000_000,
            correlate=correlate,
            **kwargs,
        )

        adapter.open()

        if not hasattr(adapter, "_profile") or adapter._profile is None:
            adapter.close()
            raise RuntimeError(
                f"Adapter {type(adapter).__name__} did not produce a C++ _profile upon open()."
            )

        return adapter, adapter._profile
    except ZeddaError:
        raise
    except Exception as e:
        raise ZeddaError(f"Scan failed: {e}") from e


def scan(
    source: Any,
    sample_size: int | None = None,
    correlate: bool = False,
    allowed_dir: str | None = None,
    **kwargs,
) -> Any:
    """Canonical scan implementation.

    Resolves the input via AdapterRegistry, calls the C++ kernel through the adapter,
    and returns a DatasetProfile.
    """
    adapter, cpp_profile = _scan_legacy(
        source,
        sample_size=sample_size,
        correlate=correlate,
        allowed_dir=allowed_dir,
        **kwargs,
    )

    try:
        # Convert C++ DatasetProfile into the canonical Python model
        is_sampled = getattr(adapter, "is_sampled", False)
        canonical = legacy_to_profile_result(cpp_profile)

        # Preserve exact evidence available from a complete in-memory frame.
        # Sampled adapters intentionally do not expose this override.
        exact_evidence = getattr(adapter, "_exact_evidence", {})
        if exact_evidence and not getattr(adapter, "is_sampled", False):
            from dataclasses import replace

            from ._models import Coverage, Metric, MetricStatus

            updated_columns = []
            for col_prof in canonical.columns:
                evidence = exact_evidence.get(col_prof.name)
                if evidence is None:
                    updated_columns.append(col_prof)
                    continue
                rows_total = canonical.num_rows
                metrics = dict(col_prof.metrics)
                metrics["unique"] = Metric(
                    value=evidence["unique_count"],
                    status=MetricStatus.EXACT,
                    coverage=Coverage(rows_examined=rows_total, rows_total=rows_total),
                    method="pandas_exact",
                )
                values = evidence["distinct_values"]
                updated_columns.append(
                    replace(
                        col_prof,
                        metrics=metrics,
                        top_values=list(values),
                        distinct_values_val=list(values),
                        distinct_overflowed_val=evidence["distinct_overflowed"],
                    )
                )
            canonical = replace(canonical, columns=updated_columns)

        # Merge Parquet footer metrics (F-05 fix)
        if hasattr(adapter, "_footer_metrics"):
            for col_prof in canonical.columns:
                if col_prof.name in adapter._footer_metrics:
                    fm = adapter._footer_metrics[col_prof.name]
                    for k, v in fm.items():
                        col_prof.metrics[k] = v
    finally:
        adapter.close()

    return canonical


def profile(
    source: Any,
    sample_size: int | None = None,
    correlate: bool = False,
    allowed_dir: str | None = None,
    **kwargs,
) -> Any:
    """Canonical profile implementation.

    Scans the dataset and prints a formatted report to the console.
    """
    from ._compat import legacy_to_profile_result
    from ._profile_print import _print_report

    adapter, cpp_profile = _scan_legacy(
        source, sample_size=sample_size, correlate=correlate, **kwargs
    )

    try:
        canonical = legacy_to_profile_result(cpp_profile)
        _print_report(canonical)
        return canonical
    finally:
        adapter.close()
