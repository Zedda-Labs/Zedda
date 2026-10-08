import pytest
import pandas as pd
import zedda as zd

TOKENS = [
    "",
    " ",
    "  \t  ",
    "NA",
    "na",
    "N/A",
    "null",
    "NULL",
    "Null",
    "nan",
    "NaN",
    "none",
    "None",
    "NONE",
    "#N/A",
    "?",
    "unknown",
    "-",
    "--",
]

EXPECTED_ZEDDA_NULL = {
    "": True,
    " ": True,
    "  \t  ": True,
    "NA": True,
    "na": True,
    "N/A": True,
    "null": True,
    "NULL": True,
    "Null": True,
    "nan": True,
    "NaN": True,
    "none": True,
    "None": True,
    "NONE": True,
    "#N/A": True,
    "?": True,
    "unknown": False,
    "-": False,
    "--": False,
}

@pytest.mark.parametrize("token", TOKENS)
def test_null_token_parity_across_paths(tmp_path, token):
    # 1. Single-thread mmap path (<16KB)
    f_mmap = tmp_path / f"mmap_{hash(token)}.csv"
    f_mmap.write_text(f"c1,val\nx,{token}\ny,data\n", encoding="utf-8")
    prof_mmap = zd.scan(str(f_mmap))
    mmap_is_null = prof_mmap.columns[1].null_count > 0

    # 2. Single-thread fallback fgets path (>=16KB with embedded newline)
    f_fgets = tmp_path / f"fgets_{hash(token)}.csv"
    lines = ["c1,val\n", f'"note\nnewline",{token}\n']
    for i in range(2500):
        lines.append(f"{i},data\n")
    f_fgets.write_text("".join(lines), encoding="utf-8")
    assert f_fgets.stat().st_size >= 16384
    prof_fgets = zd.scan(str(f_fgets))
    fgets_is_null = prof_fgets.columns[1].null_count > 0

    # 3. Multithread path (>=16KB without embedded newlines)
    f_thread = tmp_path / f"thread_{hash(token)}.csv"
    lines = ["c1,val\n", f"row1,{token}\n"]
    for i in range(2500):
        lines.append(f"{i},data\n")
    f_thread.write_text("".join(lines), encoding="utf-8")
    assert f_thread.stat().st_size >= 16384
    prof_thread = zd.scan(str(f_thread))
    thread_is_null = prof_thread.columns[1].null_count > 0

    # All Zedda C++ paths must agree
    assert mmap_is_null == fgets_is_null == thread_is_null, (
        f"Zedda C++ path disagreement for token {repr(token)}: "
        f"mmap={mmap_is_null}, fgets={fgets_is_null}, thread={thread_is_null}"
    )

    # Must match expected Zedda specification
    expected = EXPECTED_ZEDDA_NULL[token]
    assert mmap_is_null == expected, (
        f"Token {repr(token)} expected null={expected}, got {mmap_is_null}"
    )

def test_pandas_disagreements_recorded(tmp_path):
    # Parity check vs pandas default read_csv na_values
    disagreements = []
    for token in TOKENS:
        f = tmp_path / f"pd_{hash(token)}.csv"
        f.write_text(f"c1,val\nx,{token}\ny,data\n", encoding="utf-8")
        df = pd.read_csv(str(f), keep_default_na=True)
        pd_is_null = bool(df["val"].isna().iloc[0])
        zd_is_null = EXPECTED_ZEDDA_NULL[token]
        if pd_is_null != zd_is_null:
            disagreements.append((token, f"zedda={zd_is_null}", f"pandas={pd_is_null}"))

    # Expected divergence: pandas does not treat 'Null', 'none', 'NONE', '?', or whitespace as NA by default
    divergent_tokens = [t for t, _, _ in disagreements]
    assert " " in divergent_tokens
    assert "?" in divergent_tokens
    assert "Null" in divergent_tokens
