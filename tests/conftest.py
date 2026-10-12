"""Pytest root configuration.

Excludes standalone script-style test files from pytest collection.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

collect_ignore = [
    "test_phase3.py",
    "test_ask_patterns.py",
    "test_hotfix_0_4_5.py",
]


def pytest_configure(config) -> None:
    repo_root = Path(__file__).parent.parent
    audit_dir = repo_root / "tests" / "fixtures" / "audit"
    if not (audit_dir / "tiny.csv").exists():
        script_path = repo_root / "tests" / "scripts" / "generate_audit_fixtures.py"
        if script_path.exists():
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "generate_audit_fixtures", script_path
            )
            if spec and spec.loader:
                gen_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(gen_mod)
                gen_mod.generate_fixtures()

    """Session-start guard: FAIL (not skip) if the loaded fasteda_core binary was
    built from a different source state than the current workspace.

    FIX X-02 / step-4: This guard prevents the class of bug where loop commits
    modify C++ source but the installed .pyd is stale, causing C++ tests to
    test the wrong binary and pass on dead code.
    """
    try:
        import zedda.fasteda_core as _core
    except ImportError:
        # If the extension cannot be imported at all, pytest will fail later
        # with a more helpful import error -- don't double-report here.
        return

    if os.environ.get("ZEDDA_SKIP_BINARY_GUARD") == "1":
        sys.stderr.write(
            "\nWARNING: ZEDDA_SKIP_BINARY_GUARD=1 is set. Running tests against potentially stale C++ binary!\n\n"
        )
        return

    try:
        build_hash = _core.build_source_hash()
    except AttributeError:
        build_hash = "missing (old binary)"

    repo_root = Path(__file__).parent.parent

    # Compute current source hash identical to CMake
    import hashlib
    import glob

    files = (
        glob.glob((repo_root / "src/**/*.cpp").as_posix(), recursive=True)
        + glob.glob((repo_root / "src/**/*.hpp").as_posix(), recursive=True)
        + glob.glob((repo_root / "include/**/*.hpp").as_posix(), recursive=True)
        + [(repo_root / "CMakeLists.txt").as_posix()]
    )

    files.sort()
    combined = ""
    for f in files:
        rel_path = Path(f).relative_to(repo_root).as_posix()
        try:
            content = Path(f).read_bytes().replace(b"\r\n", b"\n")
            f_hash = hashlib.sha256(content).hexdigest()
            combined += f"{rel_path}:{f_hash}\n"
        except OSError:
            pass

    current_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()

    # Print both hashes if they match (as required by M2 demo)
    if build_hash == current_hash:
        print(f"Build hash matches Python hash: {current_hash}")

    if build_hash != current_hash:
        raise RuntimeError(
            f"\n\n"
            f"STALE BINARY GUARD TRIGGERED — refusing to run tests.\n"
            f"\n"
            f"  fasteda_core binary : {_core.__file__}\n"
            f"  build source hash   : {build_hash}\n"
            f"  current source hash : {current_hash}\n"
            f"\n"
            f"The installed .pyd was built from different C++ source content.\n"
            f"Rebuild with:\n"
            f"  .venv\\Scripts\\pip.exe install --no-build-isolation -e . "
            f'--config-settings="cmake.build-type=Release"\n'
            f"\n"
            f"This guard exists to prevent tests from silently passing against\n"
            f"stale code (the root cause of the B3 whitespace-token failures\n"
            f"and the session mismatch identified in the CTO probe).\n"
        )
