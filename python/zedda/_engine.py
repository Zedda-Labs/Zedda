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

    Used by scan() and report-related helpers to resolve adapter inputs.
    """
    from pathlib import Path

    from ._errors import ZeddaError

    try:
        if sample_size is not None and sample_size <= 0:
            raise ValueError("sample_size must be greater than zero")
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
        # Convert C++ DatasetProfile into the canonical Python model in a single pass.
        # Preserve exact evidence available from a complete in-memory frame (non-sampled),
        # and merge Parquet footer metrics (F-05 fix) without multi-pass dataclass copying.
        is_sampled = getattr(adapter, "is_sampled", False)
        exact_evidence = (
            getattr(adapter, "_exact_evidence", None) if not is_sampled else None
        )
        footer_metrics = getattr(adapter, "_footer_metrics", None)

        canonical = legacy_to_profile_result(
            cpp_profile,
            exact_evidence=exact_evidence,
            footer_metrics=footer_metrics,
        )
    finally:
        adapter.close()

    return canonical
