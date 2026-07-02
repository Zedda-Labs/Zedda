import sys

import pyarrow as pa
import pyarrow.parquet as pq
import zedda as zd


def main():
    print("Creating test.parquet...")
    table = pa.table(
        {
            "a": [1, 2, 3, 4, None],
            "b": ["apple", "banana", "apple", None, "orange"],
            "c": [10.5, 20.2, None, 40.5, 50.1],
        }
    )
    pq.write_table(table, "test.parquet")

    print("Profiling test.parquet with zedda...")
    try:
        p = zd.profile("test.parquet")
        print("Success! Rows:", p.num_rows, "Cols:", p.num_cols)
    except Exception as e:
        print("Error:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
