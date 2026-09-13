from __future__ import annotations

from typing import Any

from zedda._models import ColumnProfile, Coverage, DatasetProfile, Metric, MetricStatus


def legacy_to_profile_result(
    legacy_profile: Any,
    exact_evidence: dict[str, Any] | None = None,
    footer_metrics: dict[str, dict[str, Any]] | None = None,
) -> DatasetProfile:
    """
    Bridge function to convert C++ DatasetProfile from the
    C++ bindings into the new canonical DatasetProfile data model.

    Supports optional exact_evidence and footer_metrics for single-pass construction.
    """
    cols = []

    # Check what fields are actually available in the legacy profile
    is_sampled = getattr(legacy_profile, "is_sampled", False)
    num_rows = legacy_profile.num_rows

    total_nulls = 0
    metric_attrs = (
        ("mean", "mean"),
        ("val_min", "min"),
        ("val_max", "max"),
        ("std", "std"),
        ("stddev", "std"),
        ("min_str_len", "min_len"),
        ("max_str_len", "max_len"),
    )

    for c in legacy_profile.columns:
        col_name = c.name
        metrics = {}
        unsupported_types = list(getattr(c, "unsupported_types", []))
        evidence_status = (
            MetricStatus.UNSUPPORTED
            if unsupported_types
            else (MetricStatus.EXACT if not is_sampled else MetricStatus.SAMPLED)
        )

        # null_pct
        null_c = getattr(c, "null_count", 0)
        total_nulls += null_c
        valid_c = getattr(c, "valid_count", getattr(c, "non_null_count", 0))
        invalid_c = getattr(c, "invalid_count", 0)
        parse_error_c = getattr(c, "parse_error_count", 0)
        total_c = getattr(
            c,
            "total_count",
            null_c + valid_c + invalid_c + parse_error_c,
        )
        null_p = round((null_c / total_c) * 100, 2) if total_c > 0 else 0.0

        cov = Coverage(rows_examined=total_c, rows_total=num_rows)

        metrics["null_pct"] = Metric(
            value=null_p,
            status=evidence_status,
            coverage=cov,
            method="legacy",
            unsupported_fields=unsupported_types,
            parse_errors=getattr(c, "type_mismatch_count", 0),
        )

        metrics["valid_count"] = Metric(
            value=valid_c,
            status=evidence_status,
            coverage=cov,
            method="legacy",
            unsupported_fields=unsupported_types,
        )
        metrics["invalid_count"] = Metric(
            value=invalid_c,
            status=evidence_status,
            coverage=cov,
            method="legacy",
            unsupported_fields=unsupported_types,
        )

        for legacy_attr, can_attr in metric_attrs:
            if hasattr(c, legacy_attr):
                metrics[can_attr] = Metric(
                    value=getattr(c, legacy_attr),
                    status=evidence_status,
                    coverage=cov,
                    method="legacy",
                    unsupported_fields=unsupported_types,
                )

        evidence = exact_evidence.get(col_name) if exact_evidence else None
        if evidence is not None:
            metrics["unique"] = Metric(
                value=evidence["unique_count"],
                status=MetricStatus.EXACT,
                coverage=Coverage(rows_examined=num_rows, rows_total=num_rows),
                method="pandas_exact",
            )
            top_vals = list(evidence["distinct_values"])
            distinct_values_val = top_vals
            distinct_overflowed_val = evidence["distinct_overflowed"]
        else:
            unique_val = getattr(c, "unique_exact", -1)
            if (
                unique_val != -1
                and getattr(c, "exact_unique_valid", False)
                and not is_sampled
            ):
                status = MetricStatus.EXACT
                method = "exact"
            else:
                unique_val = getattr(c, "unique_approx", 0)
                status = (
                    MetricStatus.UNSUPPORTED
                    if unsupported_types
                    else (
                        MetricStatus.SAMPLED if is_sampled else MetricStatus.APPROXIMATE
                    )
                )
                method = "HLL"

            metrics["unique"] = Metric(
                value=unique_val,
                status=status,
                coverage=cov,
                method=method,
                unsupported_fields=unsupported_types,
            )

            top = getattr(c, "top_values", [])
            top_vals = [getattr(v, "value", v) for v in top]
            distinct_values_val = list(getattr(c, "distinct_values", []))
            distinct_overflowed_val = bool(getattr(c, "distinct_overflowed", False))

        if footer_metrics and col_name in footer_metrics:
            for k, v in footer_metrics[col_name].items():
                metrics[k] = v

        # Build ColumnProfile
        cp = ColumnProfile(
            name=col_name,
            type_str=c.type_str,
            metrics=metrics,
            top_values=top_vals,
            histogram_bins_val=list(getattr(c, "histogram_bins", [])),
            skewness_val=float(getattr(c, "skewness", 0.0)),
            kurtosis_val=float(getattr(c, "kurtosis", 0.0)),
            exact_numeric_overflowed_val=bool(
                getattr(c, "exact_numeric_overflowed", False)
            ),
            distinct_overflowed_val=distinct_overflowed_val,
            distinct_values_val=distinct_values_val,
            unsupported_types_val=unsupported_types,
        )
        cols.append(cp)

    total_cells = legacy_profile.num_rows * legacy_profile.num_cols
    overall_null_pct = (
        round((total_nulls / total_cells) * 100, 2) if total_cells > 0 else 0.0
    )

    overall = {
        "null_pct": Metric(
            value=overall_null_pct,
            status=MetricStatus.EXACT if not is_sampled else MetricStatus.SAMPLED,
            coverage=Coverage(
                rows_examined=legacy_profile.num_rows,
                rows_total=legacy_profile.num_rows,
            ),
            method="legacy",
        )
    }

    return DatasetProfile(
        file_name=legacy_profile.file_name,
        num_rows=legacy_profile.num_rows,
        num_cols=legacy_profile.num_cols,
        columns=cols,
        overall_metrics=overall,
        correlations_val=getattr(legacy_profile, "correlations", []),
    )
