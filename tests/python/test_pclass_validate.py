import zedda as zd


def test_pclass_allowed_values():
    report = zd.validate(
        "tests/data/titanic.csv", rules={"Pclass": {"allowed_values": [1, 2, 3]}}
    )

    print(f"Indeterminate: {report.indeterminate_rules}")
    print(f"Passed: {report.passed_rules}")
    print(f"Failed: {report.failed_rules}")
    for b in report.all_breaches():
        print(f"Breach: {b.column} - {b.rule} - {b.reason}")


if __name__ == "__main__":
    test_pclass_allowed_values()
