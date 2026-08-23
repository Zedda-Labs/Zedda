import pytest
import pandas as pd
import zedda as zd


def test_compare_csv(tmp_path):
    df1 = pd.DataFrame({"id": [1, 2], "val": [10.0, 20.0]})
    df2 = pd.DataFrame({"id": [1, 2], "val": [10.0, 30.0]})
    p1 = tmp_path / "1.csv"
    p2 = tmp_path / "2.csv"
    df1.to_csv(p1, index=False)
    df2.to_csv(p2, index=False)

    zd.compare(str(p1), str(p2))


def test_compare_dataframe():
    df1 = pd.DataFrame({"id": [1, 2], "val": [10.0, 20.0]})
    df2 = pd.DataFrame({"id": [1, 2], "val": [10.0, 30.0]})
    zd.compare(df1, df2)


def test_scientific_drift_metrics(tmp_path):
    import io
    from contextlib import redirect_stdout
    import numpy as np

    # Base dataset: normal distribution
    np.random.seed(42)
    df1 = pd.DataFrame({"score": np.random.normal(50, 10, 1000).astype(int)})
    # Drifted dataset: shifted and wider
    df2 = pd.DataFrame({"score": np.random.normal(60, 15, 1000).astype(int)})

    f = io.StringIO()
    with redirect_stdout(f):
        zd.compare(df1, df2)

    out = f.getvalue()

    # We should see SHIFT or DRIFT and PSI/KS/WD metrics
    assert "PSI:" in out
    assert "KS:" in out
    assert "WD:" in out
    assert "DRIFT" in out or "SHIFT" in out


def test_compare_canonical_module():
    from zedda._compare import compare as _compare_fn

    assert zd.compare is _compare_fn


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 6.3: Categorical Evidence in Drift
# ─────────────────────────────────────────────────────────────────────────────
class MockColumn:
    def __init__(
        self,
        name: str,
        type_str: str,
        mean: float = 0.0,
        val_min: float | None = None,
        val_max: float | None = None,
        unique_approx: float = 0.0,
        unique_pct: float = 0.0,
        distinct_values: list | None = None,
        distinct_overflowed: bool = False,
        histogram_bins: list | None = None,
        total_count: int = 100,
    ):
        self.name = name
        self.type_str = type_str
        self.mean = mean
        self.val_min = val_min
        self.val_max = val_max
        self.unique_approx = unique_approx
        self.unique_pct = unique_pct
        self.distinct_values = distinct_values or []
        self.distinct_overflowed = distinct_overflowed
        self.histogram_bins = histogram_bins or []
        self.total_count = total_count


def test_category_diff_complete_evidence():
    """Phase 6.3: complete categorical evidence produces EXACT diff and Jaccard."""
    from zedda._compare import compute_category_diff

    cols_a = [
        MockColumn(
            name="category",
            type_str="str",
            distinct_values=["A", "B", "C"],
            total_count=100,
        )
    ]
    cols_b = [
        MockColumn(
            name="category",
            type_str="str",
            distinct_values=["B", "C", "D"],
            total_count=100,
        )
    ]

    diffs = compute_category_diff(cols_a, cols_b)
    assert len(diffs) == 1
    d = diffs[0]
    assert d["status"] == "EXACT"
    assert d["overflowed"] is False
    assert d["new_in_b"] == ["D"]
    assert d["missing_in_b"] == ["A"]
    assert d["jaccard"] == 0.5


def test_category_diff_genuinely_empty():
    """Phase 6.3: genuinely empty datasets (0 rows) report exact match."""
    from zedda._compare import compute_category_diff

    cols_a = [
        MockColumn(name="status", type_str="str", distinct_values=[], total_count=0)
    ]
    cols_b = [
        MockColumn(name="status", type_str="str", distinct_values=[], total_count=0)
    ]

    diffs = compute_category_diff(cols_a, cols_b)
    assert len(diffs) == 1
    d = diffs[0]
    assert d["status"] == "EXACT"
    assert d["unique_a"] == 0
    assert d["unique_b"] == 0
    assert d["jaccard"] == 1.0


def test_category_diff_overflowed_indeterminate():
    """Phase 6.3: overflowed distinct values return INDETERMINATE without fabricated diff."""
    from zedda._compare import compute_category_diff

    cols_a = [
        MockColumn(
            name="uuid",
            type_str="str",
            unique_approx=500,
            distinct_overflowed=True,
            total_count=1000,
        )
    ]
    cols_b = [
        MockColumn(
            name="uuid",
            type_str="str",
            unique_approx=600,
            distinct_overflowed=True,
            total_count=1000,
        )
    ]

    diffs = compute_category_diff(cols_a, cols_b)
    assert len(diffs) == 1
    d = diffs[0]
    assert d["status"] == "INDETERMINATE"
    assert d["overflowed"] is True
    assert d["new_in_b"] == []
    assert d["missing_in_b"] == []
    assert d["jaccard"] is None
    assert "overflowed" in d["reason"]


def test_category_diff_incomplete_indeterminate():
    """Phase 6.3: missing distinct values with rows > 0 return INDETERMINATE."""
    from zedda._compare import compute_category_diff

    cols_a = [
        MockColumn(
            name="tag",
            type_str="str",
            unique_approx=10,
            distinct_values=[],
            total_count=100,
        )
    ]
    cols_b = [
        MockColumn(
            name="tag",
            type_str="str",
            unique_approx=12,
            distinct_values=[],
            total_count=100,
        )
    ]

    diffs = compute_category_diff(cols_a, cols_b)
    assert len(diffs) == 1
    d = diffs[0]
    assert d["status"] == "INDETERMINATE"
    assert d["overflowed"] is False
    assert "unavailable" in d["reason"]


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 6.4: Drift Statistical Honesty
# ─────────────────────────────────────────────────────────────────────────────
def test_distribution_shift_identical():
    """Phase 6.4: identical distributions yield PSI=0, KS=0, WD=0, is_stable=True."""
    from zedda._compare import compute_distribution_shift

    bins = [10, 20, 30, 40, 50, 40, 30, 20, 10, 5]
    cols_a = [
        MockColumn(
            name="val",
            type_str="float",
            mean=50.0,
            val_min=0.0,
            val_max=100.0,
            histogram_bins=bins,
            total_count=1000,
        )
    ]
    cols_b = [
        MockColumn(
            name="val",
            type_str="float",
            mean=50.0,
            val_min=0.0,
            val_max=100.0,
            histogram_bins=bins,
            total_count=1000,
        )
    ]

    shifts = compute_distribution_shift(cols_a, cols_b)
    assert len(shifts) == 1
    s = shifts[0]
    assert s["status"] == "EXACT"
    assert s["is_stable"] is True
    assert s["is_shift"] is False
    assert abs(s["psi"]) < 1e-6
    assert abs(s["ks_stat"]) < 1e-6
    assert abs(s["wasserstein"]) < 1e-6
    assert s["uncertainty"] == "LOW"
    assert s["sample_size_a"] == 1000
    assert s["sample_size_b"] == 1000


def test_distribution_shift_shared_grid_drift():
    """Phase 6.4: shifted distribution on common support grid detects PSI and KS drift."""
    from zedda._compare import compute_distribution_shift

    bins_a = [50, 40, 10, 0, 0, 0, 0, 0, 0, 0]  # concentrated near 0-20
    bins_b = [0, 0, 0, 0, 0, 0, 0, 10, 40, 50]  # concentrated near 80-100
    cols_a = [
        MockColumn(
            name="val",
            type_str="float",
            mean=10.0,
            val_min=0.0,
            val_max=100.0,
            histogram_bins=bins_a,
            total_count=1000,
        )
    ]
    cols_b = [
        MockColumn(
            name="val",
            type_str="float",
            mean=90.0,
            val_min=0.0,
            val_max=100.0,
            histogram_bins=bins_b,
            total_count=1000,
        )
    ]

    shifts = compute_distribution_shift(cols_a, cols_b)
    assert len(shifts) == 1
    s = shifts[0]
    assert s["is_shift"] is True
    assert s["is_stable"] is False
    assert s["psi"] > 0.2
    assert s["ks_stat"] > 0.1
    assert s["wasserstein"] > 50.0


def test_distribution_shift_insufficient_evidence():
    """Phase 6.4: missing histogram bins returns INDETERMINATE with HIGH uncertainty."""
    from zedda._compare import compute_distribution_shift

    cols_a = [
        MockColumn(
            name="val",
            type_str="float",
            mean=50.0,
            val_min=None,
            val_max=None,
            histogram_bins=[],
            total_count=10,
        )
    ]
    cols_b = [
        MockColumn(
            name="val",
            type_str="float",
            mean=50.0,
            val_min=None,
            val_max=None,
            histogram_bins=[],
            total_count=10,
        )
    ]

    shifts = compute_distribution_shift(cols_a, cols_b)
    assert len(shifts) == 1
    s = shifts[0]
    assert s["status"] == "INDETERMINATE"
    assert s["uncertainty"] == "HIGH"
    assert "Insufficient" in s["reason"]


def test_distribution_shift_uncertainty_tiers():
    """Phase 6.4: verifies sample size tiers (HIGH < 30, MODERATE < 500, LOW >= 500)."""
    from zedda._compare import compute_distribution_shift

    bins = [5, 5, 5, 5, 5, 5, 5, 5, 5, 5]
    # Small sample (N=20) -> HIGH uncertainty
    s_small = compute_distribution_shift(
        [
            MockColumn(
                name="v",
                type_str="float",
                mean=10,
                val_min=0,
                val_max=10,
                histogram_bins=bins,
                total_count=20,
            )
        ],
        [
            MockColumn(
                name="v",
                type_str="float",
                mean=10,
                val_min=0,
                val_max=10,
                histogram_bins=bins,
                total_count=20,
            )
        ],
    )[0]
    assert s_small["uncertainty"] == "HIGH"

    # Moderate sample (N=200) -> MODERATE uncertainty
    s_mod = compute_distribution_shift(
        [
            MockColumn(
                name="v",
                type_str="float",
                mean=10,
                val_min=0,
                val_max=10,
                histogram_bins=bins,
                total_count=200,
            )
        ],
        [
            MockColumn(
                name="v",
                type_str="float",
                mean=10,
                val_min=0,
                val_max=10,
                histogram_bins=bins,
                total_count=200,
            )
        ],
    )[0]
    assert s_mod["uncertainty"] == "MODERATE"

    # Large sample (N=1000) -> LOW uncertainty
    s_large = compute_distribution_shift(
        [
            MockColumn(
                name="v",
                type_str="float",
                mean=10,
                val_min=0,
                val_max=10,
                histogram_bins=bins,
                total_count=1000,
            )
        ],
        [
            MockColumn(
                name="v",
                type_str="float",
                mean=10,
                val_min=0,
                val_max=10,
                histogram_bins=bins,
                total_count=1000,
            )
        ],
    )[0]
    assert s_large["uncertainty"] == "LOW"


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 6.5: Data Quality Score Honesty
# ─────────────────────────────────────────────────────────────────────────────
def test_quality_score_heuristic_metadata():
    """Phase 6.5: quality score metadata reflects heuristic nature and methodology."""
    from zedda._profile_print import _quality_score, _quality_score_metadata

    class MockProfile:
        num_cols = 5
        overall_null_pct = 2.0
        columns = []

    p = MockProfile()
    score = _quality_score(p)
    meta = _quality_score_metadata(p)

    assert meta["score"] == score
    assert meta["is_calibrated"] is False
    assert meta["nature"] == "heuristic_estimate"
    assert "methodology" in meta
    assert meta["methodology"]["base_score"] == 100
    assert "disclaimer" in meta["methodology"]
    assert "Heuristic estimate only" in meta["methodology"]["disclaimer"]
