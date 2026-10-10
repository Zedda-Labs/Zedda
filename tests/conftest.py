"""Pytest root configuration.

Excludes standalone script-style test files from pytest collection.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

collect_ignore = [
    "test_phase3.py",
    "test_ask_patterns.py",
    "test_hotfix_0_4_5.py",
]


def pytest_configure(config) -> None:
    """Session-start guard: FAIL (not skip) if the loaded fasteda_core binary was
    built from a different git state than the current workspace.

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

    try:
        build_hash = _core.build_git_hash()
    except AttributeError:
        build_hash = "missing (old binary)"

    repo_root = Path(__file__).parent.parent
    try:
        import subprocess
        current_hash = subprocess.check_output(
            ["git", "describe", "--always", "--dirty", "--exclude=*"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        current_hash = "unknown"

    if current_hash != "unknown" and build_hash != current_hash:
        raise RuntimeError(
            f"\n\n"
            f"STALE BINARY GUARD TRIGGERED — refusing to run tests.\n"
            f"\n"
            f"  fasteda_core binary : {_core.__file__}\n"
            f"  build git hash      : {build_hash}\n"
            f"  current git hash    : {current_hash}\n"
            f"\n"
            f"The installed .pyd was built from a different commit or dirty state.\n"
            f"Rebuild with:\n"
            f"  .venv\\Scripts\\pip.exe install --no-build-isolation -e . "
            f"--config-settings=\"cmake.build-type=Release\"\n"
            f"\n"
            f"This guard exists to prevent tests from silently passing against\n"
            f"stale code (the root cause of the B3 whitespace-token failures\n"
            f"and the session mismatch identified in the CTO probe).\n"
        )
