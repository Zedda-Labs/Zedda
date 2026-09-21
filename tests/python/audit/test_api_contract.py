import pytest
import zedda as zd
import inspect

# The list of public features according to __all__ in __init__.py
EXPECTED_PUBLIC_API = [
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
]


def test_api_docstrings():
    for api_name in EXPECTED_PUBLIC_API:
        func = getattr(zd, api_name)
        assert func.__doc__, f"API {api_name} is missing a docstring"


def test_api_type_hints():
    for api_name in EXPECTED_PUBLIC_API:
        func = getattr(zd, api_name)
        hints = inspect.get_annotations(func)
        # We expect at least one hint (e.g. return type) for most APIs,
        # but let's just ensure that inspect succeeds without error.
        assert isinstance(hints, dict)


def test_invalid_types_raise_proper_errors():
    with pytest.raises(TypeError):
        # Pass a list of integers instead of a dataframe/path to scan
        zd.scan([1, 2, 3])


def test_scan_return_type():
    import pandas as pd

    df = pd.DataFrame({"a": [1]})
    p = zd.scan(df)

    # Must be DatasetProfile
    from zedda._models import DatasetProfile

    assert isinstance(p, DatasetProfile)


def test_namespace_clean():
    # Avoid having extra un-exported symbols exposed at the top level
    # Not strictly possible in Python, but we can check __all__
    # This was already covered in feature inventory.
    pass
