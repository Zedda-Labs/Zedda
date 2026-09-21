import os
from pathlib import Path
import pandas as pd
import numpy as np


def generate_fixtures():
    # Setup directories
    base_dir = Path(__file__).parent.parent / "fixtures" / "audit"
    base_dir.mkdir(parents=True, exist_ok=True)

    np.random.seed(42)

    # 1. tiny.csv - 3 rows, 3 cols
    df_tiny = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"],
            "score": [10.5, 20.0, 30.2],
        }
    )
    df_tiny.to_csv(base_dir / "tiny.csv", index=False)

    # 2. normal_business.csv - 500 rows, realistic business data
    df_normal = pd.DataFrame(
        {
            "employee_id": range(1000, 1500),
            "department": np.random.choice(
                ["Sales", "Engineering", "HR", "Marketing", "Finance"], 500
            ),
            "salary": np.random.normal(80000, 15000, 500).round(2),
            "is_active": np.random.choice([True, False], 500, p=[0.9, 0.1]),
            "join_date": pd.date_range("2015-01-01", periods=500, freq="D").astype(str),
        }
    )
    df_normal.to_csv(base_dir / "normal_business.csv", index=False)

    # 3. large.csv - 100K rows synthetic
    df_large = pd.DataFrame(
        {
            "id": range(100000),
            "val1": np.random.randn(100000),
            "val2": np.random.randint(0, 100, 100000),
            "category": np.random.choice(["A", "B", "C", "D"], 100000),
        }
    )
    df_large.to_csv(base_dir / "large.csv", index=False)

    # 4. wide.csv - 5 rows, 200 cols
    wide_data = {f"col_{i}": np.random.randn(5) for i in range(200)}
    df_wide = pd.DataFrame(wide_data)
    df_wide.to_csv(base_dir / "wide.csv", index=False)

    # 5. tall.csv - 500K rows, 3 cols
    df_tall = pd.DataFrame(
        {
            "id": range(500000),
            "cat": np.random.choice(["X", "Y"], 500000),
            "val": np.random.uniform(0, 1, 500000),
        }
    )
    df_tall.to_csv(base_dir / "tall.csv", index=False)

    # 6. mostly_null.csv - 80% null cells
    df_null = pd.DataFrame(
        {
            "col1": [1 if np.random.rand() > 0.8 else None for _ in range(100)],
            "col2": ["A" if np.random.rand() > 0.8 else None for _ in range(100)],
            "col3": [10.5 if np.random.rand() > 0.8 else None for _ in range(100)],
        }
    )
    df_null.to_csv(base_dir / "mostly_null.csv", index=False)

    # 7. duplicates.csv - 60% duplicate rows
    base_rows = pd.DataFrame({"id": range(40), "val": np.random.randn(40)})
    df_dupes = pd.concat([base_rows, base_rows, base_rows.iloc[:20]], ignore_index=True)
    df_dupes.to_csv(base_dir / "duplicates.csv", index=False)

    # 8. high_cardinality.csv - UUID-like string column
    import uuid

    df_high_card = pd.DataFrame(
        {"uuid": [str(uuid.uuid4()) for _ in range(1000)], "val": np.random.randn(1000)}
    )
    df_high_card.to_csv(base_dir / "high_cardinality.csv", index=False)

    # 9. mixed_types.csv - int/float/str/bool/date columns
    df_mixed = pd.DataFrame(
        {
            "int_col": [1, 2, 3, 4, 5],
            "float_col": [1.1, 2.2, 3.3, 4.4, 5.5],
            "str_col": ["a", "b", "c", "d", "e"],
            "bool_col": [True, False, True, False, True],
            "date_col": [
                "2023-01-01",
                "2023-01-02",
                "2023-01-03",
                "2023-01-04",
                "2023-01-05",
            ],
        }
    )
    df_mixed.to_csv(base_dir / "mixed_types.csv", index=False)

    # 10. numeric_only.csv - all numeric
    df_num_only = pd.DataFrame(
        {"i1": [1, 2, 3], "i2": [10, 20, 30], "f1": [1.1, 2.2, 3.3]}
    )
    df_num_only.to_csv(base_dir / "numeric_only.csv", index=False)

    # 11. string_only.csv - all string
    df_str_only = pd.DataFrame({"s1": ["a", "b", "c"], "s2": ["cat", "dog", "mouse"]})
    df_str_only.to_csv(base_dir / "string_only.csv", index=False)

    # 12. datetime.csv - timestamp/date columns
    df_dt = pd.DataFrame(
        {
            "date_only": ["2023-01-01", "2023-01-02", "2023-01-03"],
            "timestamp": [
                "2023-01-01 10:00:00",
                "2023-01-02 11:30:00",
                "2023-01-03 14:45:00",
            ],
        }
    )
    df_dt.to_csv(base_dir / "datetime.csv", index=False)

    # 13. unicode.csv - CJK, Arabic, emoji in column values
    df_unicode = pd.DataFrame(
        {
            "english": ["hello", "world"],
            "cjk": ["你好", "世界"],
            "arabic": ["مرحبا", "العالم"],
            "emoji": ["😀", "🌍"],
        }
    )
    df_unicode.to_csv(base_dir / "unicode.csv", index=False, encoding="utf-8")

    # 14. dirty_realworld.csv - real-world messy data patterns
    df_dirty = pd.DataFrame(
        {
            "id": ["1", "2", "3", "NULL", "5", "N/A", "7", "8", "9", "10"],
            "age": ["25", "30", "forty", "45", "", "55", "60", "65", "70", "75"],
            "salary": [
                "$50,000",
                "60000",
                "70,000.50",
                "80k",
                "90000",
                "100000",
                "110000",
                "120000",
                "130000",
                "140000",
            ],
        }
    )
    df_dirty.to_csv(base_dir / "dirty_realworld.csv", index=False)

    # 15. adversarial.csv - quoted newlines, BOM, special chars, overflow values
    with open(base_dir / "adversarial.csv", "w", encoding="utf-8-sig") as f:  # with BOM
        f.write("id,text,val\n")
        f.write('1,"line1\nline2",100\n')
        f.write('2,"has,comma",9223372036854775807\n')  # MAX_INT
        f.write('3,"has""quote",-9223372036854775808\n')  # MIN_INT
        f.write("4,normal,1.7976931348623157e+308\n")  # MAX_FLOAT

    # 16. ml_classification.csv - target + features
    df_ml = pd.DataFrame(
        {
            "feature1": np.random.randn(500),
            "feature2": np.random.rand(500),
            "feature3": np.random.choice(["A", "B", "C"], 500),
            "target": np.random.choice([0, 1], 500),
        }
    )
    df_ml.to_csv(base_dir / "ml_classification.csv", index=False)

    # 17. churn.csv - churn-style dataset
    df_churn = pd.DataFrame(
        {
            "customer_id": range(1, 101),
            "tenure_months": np.random.randint(1, 72, 100),
            "monthly_charges": np.random.uniform(20, 120, 100).round(2),
            "contract": np.random.choice(
                ["Month-to-month", "One year", "Two year"], 100
            ),
            "churn": np.random.choice(["Yes", "No"], 100, p=[0.2, 0.8]),
        }
    )
    df_churn.to_csv(base_dir / "churn.csv", index=False)

    # 18. corrupted.csv - malformed/truncated file
    with open(base_dir / "corrupted.csv", "w", encoding="utf-8") as f:
        f.write("col1,col2,col3\n")
        f.write("1,2,3\n")
        f.write("4,5\n")  # missing column
        f.write("6,7,8,9\n")  # extra column
        f.write('10,"unterminated quote\n')

    # 19. empty_header.csv - header row only
    with open(base_dir / "empty_header.csv", "w", encoding="utf-8") as f:
        f.write("col1,col2,col3\n")

    # Generate some Parquet versions
    try:
        df_normal.to_parquet(base_dir / "normal_business.parquet", index=False)
        df_large.to_parquet(base_dir / "large.parquet", index=False)
        df_mixed.to_parquet(base_dir / "mixed_types.parquet", index=False)
    except Exception as e:
        print(f"Failed to generate parquet: {e}")


if __name__ == "__main__":
    generate_fixtures()
    print("Fixtures generated successfully.")
