"""
Smoke test: verify that zedda can be imported successfully
and that the core module is accessible.
"""
import zedda as zd


def test_import_zedda():
    """zedda package must be importable."""
    assert zd is not None


def test_version_exists():
    """__version__ must be defined and non-empty."""
    assert hasattr(zd, "__version__")
    assert isinstance(zd.__version__, str)
    assert len(zd.__version__) > 0


def test_core_functions_exist():
    """All public API functions must be present after import."""
    assert callable(getattr(zd, "profile", None))
    assert callable(getattr(zd, "scan",    None))
    assert callable(getattr(zd, "warnings", None))
    assert callable(getattr(zd, "fix",     None))
    assert callable(getattr(zd, "compare", None))
    assert callable(getattr(zd, "ask",     None))