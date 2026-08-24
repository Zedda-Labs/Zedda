import zedda as zd
import sys


def capture_proof():
    print("\n=== PROOF 1: EXACT UNIQUE COUNT (Priority 0 & 1) ===")
    p = zd.scan("tests/data/titanic.csv")
    name_col = next(c for c in p.columns if c.name == "Name")
    ticket_col = next(c for c in p.columns if c.name == "Ticket")
    print(
        f"Name   - exact_valid: {name_col.exact_unique_valid}, unique_exact: {name_col.unique_exact}"
    )
    print(
        f"Ticket - exact_valid: {ticket_col.exact_unique_valid}, unique_exact: {ticket_col.unique_exact}"
    )

    print("\n=== PROOF 2: WARNINGS DEDUPLICATION (Priority 1) ===")
    try:
        from rich.console import Console
        from zedda._warnings import warnings

        warnings("tests/data/titanic.csv")
    except Exception as e:
        print(f"Error: {e}")

    print("\n=== PROOF 3: VALIDATE ALLOWED_VALUES ON NUMERICS (Priority 2) ===")
    try:
        report = zd.validate(
            "tests/data/titanic.csv", rules={"Pclass": {"allowed_values": [1, 2, 3]}}
        )
        print(f"Indeterminate: {report.indeterminate_rules}")
        print(f"Passed: {report.passed_rules}")
        print(f"Failed: {report.failed_rules}")
        for b in report.all_breaches():
            print(f"Breach: {b.column} - {b.rule} - {b.reason}")
        if not report.all_breaches():
            print("No breaches found!")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    capture_proof()
