import zedda as zd
import pathlib

def test_m4_clean_string_fidelity(tmp_path):
    csv_content = b'A,B,C,D\r\n1,1.50,9007199254740993,"quoted\nnewline"\r\n1,2.50, ,foo\r\n1,3.50,9007199254740994,bar\r\n1, ,9007199254740995,foo\r\n1,4.50,9007199254740996,bar\r\n'
    p = tmp_path / 'm4_fixture.csv'
    p.write_bytes(csv_content)
    
    # Impute missing values (will impute the 'B' and 'C' column empty space)
    zd.clean(str(p), dry_run=False, approved=True)
    
    out = p.read_bytes()
    import pandas as pd
    import io
    
    # Read both with dtype=str to avoid inference
    df_in = pd.read_csv(io.BytesIO(csv_content), dtype=str, skip_blank_lines=False, na_filter=False)
    df_out = pd.read_csv(p, dtype=str, skip_blank_lines=False, na_filter=False)
    
    # Compare untouched rows/cols
    # A should be dropped as constant! Wait, if A is constant it drops A.
    # Let's check B, C, D
    assert df_out.loc[0, 'B'] == '1.50'
    assert df_out.loc[0, 'C'] == '9007199254740993'
    assert df_out.loc[0, 'D'] == 'quoted\nnewline'
