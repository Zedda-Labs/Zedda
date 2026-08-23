__version__ = "0.4.8"

from typing import Any
from ._engine import scan
from ._compare import compare
from ._ml_ready import ml_ready
from ._warnings import warnings, collect_warnings
from ._fix import fix
from ._clean import clean
from ._merge import merge
from ._validate import validate
from ._ask import ask, answer_offline
from .report import report
from ._errors import ZeddaError
from ._profile_print import _RICH_AVAILABLE, _console
from ._constants import SAMPLED_INFO_LOCK as _SAMPLED_INFO_LOCK

# Alias export to report
export = report

class DatasetProfileWrapper:
    """Wraps C++ DatasetProfile with __repr__ to trigger _print_report.
    Temporarily retained for Phase 5.1 backwards compatibility.
    """
    def __init__(self, canonical_profile, display_name=None):
        self.canonical_profile = canonical_profile
        self.display_name = display_name or getattr(canonical_profile, "file_name", "dataset")

    def __getattr__(self, name):
        return getattr(self.canonical_profile, name)

    @property
    def __class__(self):
        from ._models import DatasetProfile
        return DatasetProfile

    def __repr__(self):
        from ._profile_print import _print_report
        import dataclasses
        # Temporarily set the file_name to display_name for the report
        temp_profile = dataclasses.replace(self.canonical_profile, file_name=self.display_name)
        _print_report(temp_profile)
        return ""

def profile(path: Any, sample_size: int | None = None, correlate: bool = False) -> Any:
    """
    Profile a file or DataFrame and print a beautiful terminal report.
    Returns a DatasetProfile object.
    """
    from ._profile_print import _print_report
    p = scan(path, sample_size=sample_size, correlate=correlate)
    _print_report(p)
    return p

__all__ = [
    "profile",
    "scan",
    "compare",
    "ml_ready",
    "warnings",
    "fix",
    "clean",
    "merge",
    "ask",
    "report",
    "validate",
    "export",
    "collect_warnings",
    "ZeddaError",
    "__version__",
]
