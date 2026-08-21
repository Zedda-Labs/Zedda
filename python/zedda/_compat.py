from zedda._models import DatasetProfile, ColumnProfile, Metric, MetricStatus, Coverage
from typing import Any

def legacy_to_profile_result(legacy_profile: Any) -> DatasetProfile:
    """
    Bridge function to convert existing DatasetProfileWrapper from the
    C++ bindings into the new canonical DatasetProfile data model.
    """
    cols = []
    
    # Check what fields are actually available in the legacy profile
    is_sampled = getattr(legacy_profile, "is_sampled", False)
    
    for c in legacy_profile.columns:
        metrics = {}
        
        # null_pct
        metrics["null_pct"] = Metric(
            value=getattr(c, "null_pct", 0.0),
            status=MetricStatus.EXACT if not is_sampled else MetricStatus.SAMPLED,
            coverage=Coverage(
                rows_examined=getattr(c, "total_count", 0),
                rows_total=legacy_profile.num_rows
            ),
            method="legacy"
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
                rows_total=legacy_profile.num_rows
            ),
            method=method
        )
        
        # Build ColumnProfile
        cp = ColumnProfile(
            name=c.name,
            type_str=c.type_str,
            metrics=metrics
        )
        cols.append(cp)
        
    return DatasetProfile(
        file_name=legacy_profile.file_name,
        num_rows=legacy_profile.num_rows,
        num_cols=legacy_profile.num_cols,
        columns=cols
    )
