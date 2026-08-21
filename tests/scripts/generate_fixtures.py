import os
import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd
import numpy as np

base_dir = "tests/fixtures/regression"
os.makedirs(base_dir, exist_ok=True)

def make_csv(name, content, encoding='utf-8'):
    with open(os.path.join(base_dir, name), 'w', encoding=encoding, newline='') as f:
        f.write(content)

# 1. quoted multiline CSV
make_csv('quoted_multiline.csv', 'id,notes\n1,"line1\nline2"\n2,normal\n3,"another\nmultiline\nrecord"\n')

# 2. BOM CSV
with open(os.path.join(base_dir, 'bom.csv'), 'wb') as f:
    f.write(b'\xef\xbb\xbfid,val\n1,a\n2,b\n')

# 3. malformed-width CSV
make_csv('malformed.csv', 'a,b,c\n1,2,3\n1,2\n1,2,3,4\n')

# 4. empty CSV
with open(os.path.join(base_dir, 'empty.csv'), 'w') as f: pass
make_csv('empty_header.csv', 'col1,col2\n')

# 5. large-integer CSV
make_csv('large_ints.csv', 'id,val\n1,9223372036854775807\n2,-9223372036854775808\n3,18446744073709551615\n')

# 6. mixed-type columns
make_csv('mixed.csv', 'val\n1\n2.5\na\n4\n')

# 7. Parquet with nulls/dates/timestamps
df = pd.DataFrame({
    'id': [1, 2, 3, 4],
    'dates': [pd.Timestamp('2020-01-01'), None, pd.Timestamp('2020-01-03'), pd.Timestamp('2020-01-04')],
    'vals': [1.1, None, 3.3, np.nan]
})
table = pa.Table.from_pandas(df)
pq.write_table(table, os.path.join(base_dir, 'types.parquet'))

# 8. Arrow IPC
with pa.OSFile(os.path.join(base_dir, 'types.arrow'), 'wb') as sink:
    with pa.RecordBatchFileWriter(sink, table.schema) as writer:
        writer.write_table(table)
