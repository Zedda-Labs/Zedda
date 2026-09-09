"""Regression fixture: large-file row/col-count fidelity.

Rationale:
  Every existing golden fixture is small (<= a few thousand rows).  During
  Phase 2 a typo that misquoted the dataset shape as
  "1,048,576 rows x 20 cols" instead of "6,362,620 rows x 31 cols" went
  undetected because no test exercised zd.scan on a genuinely large file and
  asserted p.num_rows / p.num_cols against a pre-known ground truth.

  This test closes that gap: it generates a deterministic CSV of known exact
  dimensions (> 100 k rows, string + integer + float-with-nulls columns),
  scans it, and asserts the shape is exactly correct.  The CSV is generated
  on-the-fly into pytest's tmp_path so no large binary blob lives in the repo.
"""

import csv
import math
import time

import pytest
import zedda as zd


# ── Constants ────────────────────────────────────────────────────────────────
_EXPECTED_ROWS = 150_000
_EXPECTED_COLS = (
    5  # id (int), label (str), score (float), tag (str), value (float+nulls)
)

# Generous CI ceiling: ~30 s on the slowest CI runner.  The file is ~18 MB;
# Phase-2 build processes bench_100k (4.4 MB) in < 0.5 s so 30 s is a 60x
# safety margin for CI cold-start overhead.
_CI_TIME_CEILING_S = 30.0

_LABELS = ["alpha", "beta", "gamma", "delta", "epsilon"]
_TAGS = ["low", "medium", "high"]
_NULL_EVERY_N = 7  # inject a null in the "value" float column every 7th row


# ── Fixture generator ────────────────────────────────────────────────────────
def _generate_csv(path: str) -> None:
    """Write a deterministic CSV with _EXPECTED_ROWS rows and _EXPECTED_COLS columns."""
    lines = ["id,label,score,tag,value\n"]
    for i in range(_EXPECTED_ROWS):
        label = _LABELS[i % len(_LABELS)]
        tag = _TAGS[i % len(_TAGS)]
        score = f"{math.sin(i / 100.0) * 1000.0:.6f}"
        val = "" if (i % _NULL_EVERY_N == 0) else f"{math.cos(i / 50.0) * 500.0:.4f}"
        lines.append(f"{i},{label},{score},{tag},{val}\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)


# ── Test ─────────────────────────────────────────────────────────────────────
def test_large_file_row_col_count_fidelity(tmp_path):
    """zd.scan on a generated 150 k-row, 5-col CSV must return the exact known shape.

    This is the regression that would have caught the Phase-2 post-merge
    documentation typo (1,048,576/20 vs 6,362,620/31) had such a test existed
    for the real dataset.  It does NOT use golden-JSON snapshots — it uses
    direct, hard-coded assertions so the test cannot pass silently with a wrong
    value.
    """
    csv_file = tmp_path / "large_shape_fixture.csv"
    _generate_csv(str(csv_file))

    t0 = time.perf_counter()
    profile = zd.scan(str(csv_file))
    elapsed = time.perf_counter() - t0

    # ── Shape assertions (the whole point of this test) ──────────────────────
    assert profile.num_rows == _EXPECTED_ROWS, (
        f"Expected {_EXPECTED_ROWS:,} rows, got {profile.num_rows:,}. "
        "This indicates a row-counting regression in ProfileBuilder."
    )
    assert profile.num_cols == _EXPECTED_COLS, (
        f"Expected {_EXPECTED_COLS} cols, got {profile.num_cols}. "
        "This indicates a column-counting regression in ProfileBuilder."
    )

    # ── Column-name sanity (guards against header being dropped/duplicated) ──
    col_names = [c.name for c in profile.columns]
    assert col_names == ["id", "label", "score", "tag", "value"], (
        f"Column names mismatch: {col_names}"
    )

    # ── CI timing guardrail ───────────────────────────────────────────────────
    assert elapsed < _CI_TIME_CEILING_S, (
        f"Scan of {_EXPECTED_ROWS:,}-row CSV took {elapsed:.2f}s "
        f"(ceiling {_CI_TIME_CEILING_S}s). "
        "This may indicate a performance regression."
    )
