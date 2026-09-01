import pytest
import pandas as pd
import zedda as zd
from zedda._fix import generate_fix_code


def test_fix_apply_no_conflicting_column_actions():
    """
    Test that generated fix code does not contain conflicting actions for the same column
    (e.g., dropping a column and then trying to impute or encode it).
    """
    p = zd.scan("tests/data/titanic.csv")
    fixes = generate_fix_code(p)
    code = "\n".join(fixes["all_code"])

    # Execute the generated code on the real dataset
    df = pd.read_csv("tests/data/titanic.csv")
    local_vars = {"df": df, "pd": pd, "np": __import__("numpy")}

    # This should not raise KeyError or any exceptions
    exec(code, globals(), local_vars)  # noqa: S102
    df_new = local_vars["df"]

    # Verify exactly 1 action occurred per column that had issues.
    # For Cabin (77% nulls) -> dropped, not encoded/imputed.
    assert "Cabin" not in df_new.columns
    # For Name (100% unique) -> dropped, not encoded.
    assert "Name" not in df_new.columns
    # For PassengerId (100% unique) -> dropped.
    assert "PassengerId" not in df_new.columns
    # For Age (19.9% nulls) -> imputed.
    assert "Age" in df_new.columns
    assert df_new["Age"].isna().sum() == 0
    # For Ticket -> encoded.
    assert "Ticket" in df_new.columns
    assert (
        df_new["Ticket"].dtype == "int8"
        or df_new["Ticket"].dtype == "int16"
        or df_new["Ticket"].dtype == "int32"
        or df_new["Ticket"].dtype == "int64"
    )
