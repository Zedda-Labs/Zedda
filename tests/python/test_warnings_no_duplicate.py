import zedda as zd


def test_warnings_no_duplicate():
    p = zd.scan("tests/data/titanic.csv")
    from zedda._warnings import collect_warnings

    warnings_list = collect_warnings(p)

    # Check that we don't have multiple null warnings for Cabin (which is 77% null)
    cabin_warnings = [w for w in warnings_list if w["column"] == "Cabin"]
    null_warnings = [w for w in cabin_warnings if "null" in w["category"]]
    assert len(null_warnings) == 1, "Expected exactly 1 null warning for Cabin"
    assert null_warnings[0]["category"] == "high_nulls"

    # Check that Name (which is unique string) gets id_like_string but NOT high_cardinality
    name_warnings = [w for w in warnings_list if w["column"] == "Name"]
    assert len([w for w in name_warnings if w["category"] == "id_like_string"]) == 1
    assert len([w for w in name_warnings if w["category"] == "high_cardinality"]) == 0

    print("No duplicates found. Test passed!")
