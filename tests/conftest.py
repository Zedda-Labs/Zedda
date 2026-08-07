"""Pytest root configuration.

Excludes standalone script-style test files from pytest collection.
"""

collect_ignore = [
    "test_phase3.py",
    "test_ask_patterns.py",
    "test_hotfix_0_4_5.py",
]
