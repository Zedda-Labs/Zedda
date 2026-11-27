"""Session fixture ensuring synthetic audit datasets exist in CI and fresh checkouts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def ensure_audit_fixtures() -> None:
    """Generate audit CSV/Parquet fixtures on demand if not yet present on disk."""
    tests_root = Path(__file__).resolve().parent.parent.parent
    audit_dir = tests_root / "fixtures" / "audit"
    marker = audit_dir / "empty_header.csv"
    if marker.exists():
        return

    script_path = tests_root / "scripts" / "generate_audit_fixtures.py"
    spec = importlib.util.spec_from_file_location(
        "generate_audit_fixtures", script_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load fixture generator at {script_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.generate_fixtures()
