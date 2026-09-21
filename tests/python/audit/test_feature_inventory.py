import zedda as zd
import pytest
from zedda._errors import ZeddaError

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
    "ZeddaError",
    "__version__",
]


def test_feature_inventory_all():
    """Verify that __all__ contains exactly the expected public APIs."""
    assert hasattr(zd, "__all__"), "zedda must define __all__"
    actual_all = set(zd.__all__)
    expected_all = set(EXPECTED_PUBLIC_API)

    missing = expected_all - actual_all
    extra = actual_all - expected_all

    assert not missing, f"Missing public APIs in __all__: {missing}"
    assert not extra, f"Unexpected public APIs in __all__: {extra}"


def test_api_signatures_exist():
    """Verify all expected functions actually exist and are callable (except constants/classes)."""
    for api_name in EXPECTED_PUBLIC_API:
        if api_name in ("ZeddaError", "__version__"):
            continue
        func = getattr(zd, api_name, None)
        assert func is not None, f"Expected API {api_name} not found"
        assert callable(func), f"Expected API {api_name} to be callable"


def test_version_present():
    assert hasattr(zd, "__version__")
    assert isinstance(zd.__version__, str)
    assert zd.__version__ == "0.4.9"


def test_error_class():
    assert hasattr(zd, "ZeddaError")
    assert issubclass(zd.ZeddaError, Exception)


def test_unsupported_extensions_raise_error(tmp_path):
    """Test that scanning an unsupported file extension raises a meaningful ZeddaError."""
    bad_file = tmp_path / "data.docx"
    bad_file.write_text("dummy content")
    with pytest.raises(ZeddaError, match="Unsupported file format: .docx"):
        zd.scan(str(bad_file))


def test_empty_file_error(tmp_path):
    """Test that scanning a 0-byte file raises a meaningful ZeddaError."""
    empty_file = tmp_path / "empty.csv"
    empty_file.touch()
    with pytest.raises(ZeddaError, match="File is empty"):
        zd.scan(str(empty_file))


def test_file_not_found():
    """Test that scanning a missing file raises ZeddaError."""
    with pytest.raises(ZeddaError, match="File not found"):
        zd.scan("does_not_exist_at_all.csv")
