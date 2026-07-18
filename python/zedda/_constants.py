"""
zedda._constants — shared constants and caches.

FIX P-M2 / Batch 7: Extracted from __init__.py to reduce module size
and improve testability. These are internal implementation details
and not part of the public API.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path

# ─────────────────────────────────────────────────────────────────
#  Arrow C Data Interface struct sizes (from arrow/c/abi.h)
#  ArrowSchema / ArrowArray: 9 pointer-sized fields → 72 bytes on 64-bit.
#  We allocate 256 bytes each for safety.
# ─────────────────────────────────────────────────────────────────
ARROW_SCHEMA_SIZE = 256
ARROW_ARRAY_SIZE = 256

# ─────────────────────────────────────────────────────────────────
#  Stores (scanned_rows, total_rows) for sampled files — used by _print_report.
#  P-04: Capped at 100 entries to prevent unbounded memory growth in
#  long-running processes that profile many files.
#  FIX P-M4: Add a threading.Lock around mutation — concurrent scan()
#  calls could race on OrderedDict.popitem.
# ─────────────────────────────────────────────────────────────────
SAMPLED_INFO_MAX = 100
SAMPLED_INFO: OrderedDict = OrderedDict()
SAMPLED_INFO_LOCK = threading.Lock()


def sampled_info_set(key: str, value: tuple) -> None:
    """Store sampling info with LRU eviction when cache exceeds max size."""
    with SAMPLED_INFO_LOCK:
        SAMPLED_INFO[key] = value
        if len(SAMPLED_INFO) > SAMPLED_INFO_MAX:
            SAMPLED_INFO.popitem(last=False)


from typing import Any

def sampled_info_get(key: str, default: tuple) -> Any:
    """Thread-safe read from the sampled-info cache."""
    with SAMPLED_INFO_LOCK:
        return SAMPLED_INFO.get(key, default)


# ─────────────────────────────────────────────────────────────────
#  SEC-Q03: Extension allowlist for ask().
# ─────────────────────────────────────────────────────────────────
ASK_ALLOWED_EXT = {".csv", ".parquet", ".arrow", ".feather"}

# ─────────────────────────────────────────────────────────────────
#  SEC-Q02: Blocked OS root paths (case-insensitive path containment).
#  FIX P-H1: Use Path objects + Path.relative_to() so '/rootkit/x.csv'
#  no longer matches '/root'. Containment is checked in _ask_validate_path.
# ─────────────────────────────────────────────────────────────────
ASK_BLOCKED_ROOTS = [
    Path("/etc"),
    Path("/proc"),
    Path("/sys"),
    Path("/root"),
    Path("C:/Windows"),
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
]

# ─────────────────────────────────────────────────────────────────
#  Zedda AI pricing table (internal — never shown to user).
# ─────────────────────────────────────────────────────────────────
AI_PRICING = {
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "openai/gpt-oss-120b": {"input": 0.15, "output": 0.75},
    "openai/gpt-oss-20b": {"input": 0.10, "output": 0.50},
    "moonshotai/kimi-k2-instruct-0905": {"input": 0.55, "output": 2.20},
}

# Default AI model (internal — not exposed to user).
AI_DEFAULT_MODEL = "llama-3.3-70b-versatile"

# Default AI endpoint. FIX M-24: Make configurable via env var.
import os as _os

AI_ENDPOINT = _os.environ.get(
    "ZEDDA_AI_ENDPOINT",
    "https://api.groq.com/openai/v1/chat/completions",
)
