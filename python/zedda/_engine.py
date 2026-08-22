from typing import Any, Optional
from ._adapters.registry import AdapterRegistry
from ._compat import legacy_to_profile_result

def _scan_legacy(
    source: Any,
    sample_size: Optional[int] = None,
    correlate: bool = False,
    allowed_dir: Optional[str] = None,
    **kwargs
) -> Any:
    """
    Internal scan that returns the C++ profile object and the adapter.
    Used by profile() and _print_report() to maintain legacy formatting.
    """
    from pathlib import Path
    from . import ZeddaError
    
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
            if resolved.exists() and resolved.is_file() and resolved.stat().st_size == 0:
                raise ZeddaError(
                    f"File is empty (0 bytes): '{source}'\n"
                    "Tip: Check that the file was written correctly."
                )
                
        adapter = AdapterRegistry.resolve(
            source, 
            is_sampled=(sample_size is not None), 
            sample_size=sample_size or 1_000_000, 
            correlate=correlate,
            **kwargs
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
    sample_size: Optional[int] = None,
    correlate: bool = False,
    allowed_dir: Optional[str] = None,
    **kwargs
) -> Any:
    """
    Canonical scan implementation.
    Resolves the input via AdapterRegistry, calls the C++ kernel through the adapter,
    and returns a DatasetProfile.
    """
    adapter, cpp_profile = _scan_legacy(
        source, sample_size=sample_size, correlate=correlate, allowed_dir=allowed_dir, **kwargs
    )
    
    try:
        # Convert C++ DatasetProfile into the canonical Python model
        canonical = legacy_to_profile_result(cpp_profile)
    finally:
        adapter.close()
        
    return canonical

def profile(
    source: Any,
    sample_size: Optional[int] = None,
    correlate: bool = False,
    allowed_dir: Optional[str] = None,
    **kwargs
) -> Any:
    """
    Canonical profile implementation.
    Scans the dataset and prints a formatted report to the console.
    """
    from .__init__ import _print_report
    from ._compat import legacy_to_profile_result

    adapter, cpp_profile = _scan_legacy(
        source, sample_size=sample_size, correlate=correlate, **kwargs
    )

    try:
        canonical = legacy_to_profile_result(cpp_profile)
        _print_report(canonical)
        return canonical
    finally:
        adapter.close()
