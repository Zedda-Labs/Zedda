import zedda as zd


def test_name_unique_never_exceeds_row_count():
    p = zd.scan("tests/data/titanic.csv")
    n = next(c for c in p.columns if c.name == "Name")

    print(f"Name non_null_count: {n.non_null_count}")
    print(f"Name unique_approx: {n.unique_approx}")
    print(f"Name unique_exact: {getattr(n, 'unique_exact', 'missing')}")

    assert n.unique_approx <= n.non_null_count, (
        f"Unique count {n.unique_approx} exceeds non-null count {n.non_null_count}"
    )
    if hasattr(n, "unique_exact") and n.unique_exact != -1:
        assert n.unique_exact <= n.non_null_count
        assert n.unique_approx == n.unique_exact

    assert n.unique_approx == 891
