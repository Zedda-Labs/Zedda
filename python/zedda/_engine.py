from typing import Any, Optional
from ._adapters.registry import AdapterRegistry
from ._compat import legacy_to_profile_result

def scan(
    source: Any,
    sample_size: Optional[int] = None,
    correlate: bool = False,
    **kwargs
) -> Any:
    """
    Canonical scan implementation.
    Resolves the input via AdapterRegistry, calls the C++ kernel through the adapter,
    and returns a DatasetProfile.
    """
    adapter = AdapterRegistry.resolve(
        source, 
        is_sampled=(sample_size is not None), 
        sample_size=sample_size or 1_000_000, 
        correlate=correlate,
        **kwargs
    )
    
    adapter.open()
    
    try:
        if not hasattr(adapter, "_profile") or adapter._profile is None:
            raise RuntimeError(
                f"Adapter {type(adapter).__name__} did not produce a C++ _profile upon open()."
            )
        # Convert C++ DatasetProfile into the canonical Python model
        canonical = legacy_to_profile_result(adapter._profile)
    finally:
        adapter.close()
        
    return canonical

def profile(
    source: Any,
    sample_size: Optional[int] = None,
    correlate: bool = False,
    **kwargs
) -> None:
    """
    Canonical profile implementation.
    Scans the dataset and prints a formatted report to the console.
    """
    from .__init__ import _print_report
    
    p = scan(
        source,
        sample_size=sample_size,
        correlate=correlate,
        **kwargs
    )
    _print_report(p)
