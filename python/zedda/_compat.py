from zedda._models import DatasetProfile, ColumnProfile, Metric, MetricStatus, Coverage
from typing import Any


def legacy_to_profile_result(legacy_profile: Any) -> DatasetProfile:
    """
    Bridge function to convert C++ DatasetProfile from the
    C++ bindings into the new canonical DatasetProfile data model.
    """
    cols = []

    # Check what fields are actually available in the legacy profile
    is_sampled = getattr(legacy_profile, "is_sampled", False)

    for c in legacy_profile.columns:
        metrics = {}

        # null_pct
        null_c = getattr(c, "null_count", 0)
        non_null_c = getattr(c, "non_null_count", 0)
        total_c = null_c + non_null_c
        null_p = round((null_c / total_c) * 100, 2) if total_c > 0 else 0.0

        metrics["null_pct"] = Metric(
            value=null_p,
            status=MetricStatus.EXACT if not is_sampled else MetricStatus.SAMPLED,
            coverage=Coverage(
                rows_examined=total_c, rows_total=legacy_profile.num_rows
            ),
            method="legacy",
            parse_errors=getattr(c, "type_mismatch_count", 0),
        )

        metric_map = {
            "mean": "mean",
            "val_min": "min",
            "val_max": "max",
            "std": "std",
            "min_str_len": "min_len",
            "max_str_len": "max_len",
        }
        for legacy_attr, can_attr in metric_map.items():
            if hasattr(c, legacy_attr):
                metrics[can_attr] = Metric(
                    value=getattr(c, legacy_attr),
                    status=MetricStatus.EXACT
                    if not is_sampled
                    else MetricStatus.SAMPLED,
                    coverage=Coverage(
                        rows_examined=getattr(c, "total_count", 0),
                        rows_total=legacy_profile.num_rows,
                    ),
                    method="legacy",
                )

        # unique_approx
        unique_val = getattr(c, "unique_exact", -1)
        if unique_val != -1 and getattr(c, "exact_unique_valid", False):
            status = MetricStatus.EXACT
            method = "exact"
        else:
            unique_val = getattr(c, "unique_approx", 0)
            status = MetricStatus.APPROXIMATE
            method = "HLL"

        metrics["unique"] = Metric(
            value=unique_val,
            status=status,
            coverage=Coverage(
                rows_examined=getattr(c, "total_count", 0),
                rows_total=legacy_profile.num_rows,
            ),
            method=method,
        )

        # top_values
        top = getattr(c, "top_values", [])
        top_vals = [getattr(v, "value", v) for v in top]

        # Build ColumnProfile
        cp = ColumnProfile(
            name=c.name,
            type_str=c.type_str,
            metrics=metrics,
            top_values=top_vals,
            histogram_bins_val=list(getattr(c, "histogram_bins", [])),
            skewness_val=float(getattr(c, "skewness", 0.0)),
            kurtosis_val=float(getattr(c, "kurtosis", 0.0)),
            exact_numeric_overflowed_val=bool(
                getattr(c, "exact_numeric_overflowed", False)
            ),
            distinct_overflowed_val=bool(getattr(c, "distinct_overflowed", False)),
        )
        cols.append(cp)

    overall = {}

    total_nulls = sum(getattr(c, "null_count", 0) for c in legacy_profile.columns)
    total_cells = legacy_profile.num_rows * legacy_profile.num_cols
    overall_null_pct = (
        round((total_nulls / total_cells) * 100, 2) if total_cells > 0 else 0.0
    )

    overall["null_pct"] = Metric(
        value=overall_null_pct,
        status=MetricStatus.EXACT if not is_sampled else MetricStatus.SAMPLED,
        coverage=Coverage(
            rows_examined=legacy_profile.num_rows, rows_total=legacy_profile.num_rows
        ),
        method="legacy",
    )

    return DatasetProfile(
        file_name=legacy_profile.file_name,
        num_rows=legacy_profile.num_rows,
        num_cols=legacy_profile.num_cols,
        columns=cols,
        overall_metrics=overall,
        correlations_val=getattr(legacy_profile, "correlations", []),
    )
