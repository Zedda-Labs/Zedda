import zedda as zd
import math

def test_f01_stddev_canonical_mapping():
    profile = zd.scan("tests/data/titanic.csv")
    age_col = next((c for c in profile.columns if c.name == "Age"), None)
    
    assert age_col is not None, "Age column not found"
    assert hasattr(age_col, "std"), "canonical 'std' property missing"
    
    std_val = age_col.std
    assert std_val is not None, "std is None, mapping failed"
    assert std_val != 0, "std is 0, mapping failed"
    
    # Titanic Age stddev is ~14.5
    assert math.isclose(std_val, 14.5, abs_tol=0.2), f"Expected std ~14.5, got {std_val}"
