from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from zedda._compat import legacy_to_profile_result
from zedda._models import ColumnProfile, Coverage, Metric, MetricStatus


def test_ai_insights_cli_path_uses_internal_helpers(monkeypatch):
    import zedda.ai_insights as ai_insights
    from zedda.cli import _add_ai_insights

    result = object()
    monkeypatch.setenv("ZEDDA_AI_KEY", "test-key")

    with (
        patch(
            "zedda._ask._build_ask_context",
            return_value='{"profile": true}',
        ) as build_context,
        patch(
            "zedda._ask._ask_zedda_ai",
            return_value=("healthy", None),
        ) as ask_ai,
        patch("zedda.cli.console.print") as print_console,
    ):
        _add_ai_insights(result)

    build_context.assert_called_once()
    ask_ai.assert_called_once()
    print_console.assert_called_once()
    assert ai_insights.get_insights.__module__ == "zedda.ai_insights"


def _legacy_column(**values):
    defaults = {
        "name": "value",
        "type_str": "int",
        "total_count": 3,
        "null_count": 1,
        "valid_count": 1,
        "invalid_count": 1,
        "parse_error_count": 0,
        "type_mismatch_count": 1,
        "unique_approx": 1,
        "unique_exact": -1,
        "exact_unique_valid": False,
        "top_values": [],
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


@pytest.mark.parametrize(
    ("column", "expected_null_pct", "expected_valid", "expected_invalid"),
    [
        (_legacy_column(), 33.33, 1, 1),
        (
            _legacy_column(total_count=3, null_count=0, valid_count=3, invalid_count=0),
            0.0,
            3,
            0,
        ),
        (
            _legacy_column(total_count=3, null_count=3, valid_count=0, invalid_count=0),
            100.0,
            0,
            0,
        ),
        (
            _legacy_column(total_count=3, null_count=0, valid_count=0, invalid_count=3),
            0.0,
            0,
            3,
        ),
        (
            _legacy_column(total_count=5, null_count=2, valid_count=1, invalid_count=2),
            40.0,
            1,
            2,
        ),
    ],
)
def test_canonical_counts_keep_nulls_and_invalid_rows_separate(
    column, expected_null_pct, expected_valid, expected_invalid
):
    profile = SimpleNamespace(
        file_name="fixture.csv",
        num_rows=column.total_count,
        num_cols=1,
        is_sampled=False,
        columns=[column],
    )

    canonical = legacy_to_profile_result(profile)
    result = canonical.columns[0]

    assert result.metrics["null_pct"].value == expected_null_pct
    assert result.metrics["null_pct"].coverage.rows_examined == column.total_count
    assert result.valid_count == expected_valid
    assert result.invalid_count == expected_invalid


def test_unique_pct_uses_unique_metric_coverage():
    column = ColumnProfile(
        name="value",
        type_str="int",
        metrics={
            "null_pct": Metric(
                value=0.0,
                status=MetricStatus.EXACT,
                coverage=Coverage(rows_examined=100, rows_total=100),
                method="footer",
            ),
            "unique": Metric(
                value=4,
                status=MetricStatus.SAMPLED,
                coverage=Coverage(rows_examined=4, rows_total=100),
                method="HLL",
            ),
        },
    )

    assert column.unique_pct == 100.0
