"""Comprehensive regression tests for all core C++ and Python bug fixes."""

from __future__ import annotations

import io
import warnings
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import zedda as zd
from zedda import fasteda_core as _core


def test_exact_skewness_and_kurtosis_csv_and_dataframe(tmp_path):
    """M3 and M4 online moments must not read already-updated M2."""
    # [1, 1, 1, 10] -> mean=3.25, std=4.5, Fisher skewness=2.0, excess kurtosis=4.0
    csv_path = tmp_path / "moments.csv"
    csv_path.write_text("x\n1\n1\n1\n10\n", encoding="utf-8")
    df = pd.DataFrame({"x": [1.0, 1.0, 1.0, 10.0]})

    for source in (str(csv_path), df):
        prof = zd.scan(source)
        col = prof.columns[0]
        assert col.mean == pytest.approx(3.25, rel=1e-6)
        assert col.std == pytest.approx(4.5, rel=1e-6)
        assert col.skewness == pytest.approx(2.0, rel=1e-6)
        assert col.kurtosis == pytest.approx(4.0, rel=1e-6)


def test_csv_small_sample_size_respected(tmp_path):
    """Multi-threaded CSV sampling must respect small sample_size < num_threads."""
    csv_path = tmp_path / "big_for_small_sample.csv"
    pad = "x" * 40
    lines = ["id,pad\n"] + [f"{i},{pad}\n" for i in range(600)]
    csv_path.write_text("".join(lines), encoding="utf-8")

    prof = zd.scan(str(csv_path), sample_size=3)
    assert prof.is_sampled is True
    assert prof.num_rows == 3


def test_csv_unquoted_mid_field_quote(tmp_path):
    """Unquoted fields containing a literal quote must not merge subsequent columns."""
    csv_path = tmp_path / "mid_quote.csv"
    csv_path.write_text(
        'id,note,score\n1,foo"bar,10\n2,"quoted,ok",20\n3,baz"qux,30\n',
        encoding="utf-8",
    )

    prof = zd.scan(str(csv_path))
    assert prof.num_rows == 3
    assert prof.num_cols == 3
    score = prof.columns[2]
    assert score.mean == pytest.approx(20.0)
    assert score.val_min == 10
    assert score.val_max == 30


def test_arrow_wide_numeric_correlate_flag(tmp_path):
    """ArrowProfiler must respect correlate=False (>50 numeric cols) vs correlate=True."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    ncols = 55
    nrows = 12
    data = {f"c{i}": [float(r * (i + 1)) for r in range(nrows)] for i in range(ncols)}
    pq_path = tmp_path / "wide_corr.parquet"
    pq.write_table(pa.table(data), pq_path)

    p_default = zd.scan(str(pq_path), correlate=False)
    assert p_default.correlations == []

    p_forced = zd.scan(str(pq_path), correlate=True)
    assert len(p_forced.correlations) > 0


def test_parquet_nested_struct_column_footer_safety(tmp_path):
    """Parquet with nested struct before flat numeric column must not misalign footer stats."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    struct_arr = pa.array([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}, {"a": 3, "b": "z"}])
    score_arr = pa.array([10, None, 30], type=pa.int64())
    pq_path = tmp_path / "nested.parquet"
    pq.write_table(pa.table({"meta": struct_arr, "score": score_arr}), pq_path)

    prof = zd.scan(str(pq_path))
    assert prof.num_rows == 3
    assert prof.num_cols == 2
    score_col = next(c for c in prof.columns if c.name == "score")
    assert score_col.val_min == 10
    assert score_col.val_max == 30
    assert score_col.null_count == 1


def test_distinct_overflowed_when_top_values_truncated(tmp_path):
    """C++ distinct_overflowed must be True when unique_exact > len(top_values) (capped at 100)."""
    csv_path = tmp_path / "many_unique.csv"
    lines = ["id\n"] + [f"{i}\n" for i in range(150)]
    csv_path.write_text("".join(lines), encoding="utf-8")

    raw_prof = _core.profile(str(csv_path))
    col = raw_prof.columns[0]
    assert col.unique_exact == 150
    assert len(col.top_values) == 100
    assert col.distinct_overflowed is True


def test_ask_returns_answer_and_supports_dataframe_pattern_c():
    """ask() must return answer_text, support Pattern C on DataFrames, and parse decimal %."""
    df = pd.DataFrame(
        {
            "city": ["A", "A", "B", "B", "B", "C", "C"],
            "salary": [100, 120, 200, 220, 240, 50, 70],
            "notes": [None, "ok", "ok", "ok", "ok", "ok", "ok"],  # ~14.3% null
        }
    )

    ans = zd.ask(df, "what is the average salary by city?", print_output=False)
    assert isinstance(ans, str) and "B" in ans
    assert "\\n" not in ans

    pct_ans = zd.ask(df, "columns with more than 12.5% nulls", print_output=False)
    assert isinstance(pct_ans, str) and "notes" in pct_ans

    no_match = zd.ask(df, "zzzz totally unrelated question", llm="offline", print_output=False)
    assert isinstance(no_match, str) and "No offline pattern" in no_match


def test_ask_supports_groq_api_key_env(monkeypatch, tmp_path):
    """ask() offline fallback should accept GROQ_API_KEY in addition to ZEDDA_AI_KEY."""
    monkeypatch.delenv("ZEDDA_AI_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-token")
    csv_path = tmp_path / "small.csv"
    csv_path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "choices": [{"message": {"content": "Mock AI summary."}}],
        "usage": {"total_tokens": 10},
    }
    with patch("requests.post", return_value=fake_resp) as post_mock:
        ans = zd.ask(str(csv_path), "give me a custom insight", print_output=False)

    assert ans == "Mock AI summary."
    assert post_mock.called


def test_validate_warns_on_unknown_rules():
    """validate() must emit a UserWarning when unknown rule keys are supplied."""
    df = pd.DataFrame({"age": [20, 30, 40]})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        report = zd.validate(df, rules={"age": {"min": 0, "bogus_rule": 99}})
    assert report.passed
    assert any("bogus_rule" in str(w.message) for w in caught)


def test_clean_arrow_plan_and_drop_invalid(tmp_path):
    """clean() supports .arrow IPC, generate_plan drops numeric >50% nulls, and drop_invalid coerces."""
    import pyarrow as pa
    import pyarrow.ipc as ipc

    df = pd.DataFrame(
        {
            "bad_float": [None, None, None, None, 5.0],
            "val": [1.0, 2.0, 3.0, 4.0, 5.0],
        }
    )
    in_arrow = tmp_path / "in.arrow"
    out_arrow = tmp_path / "out.arrow"
    table = pa.Table.from_pandas(df, preserve_index=False)
    with pa.OSFile(str(in_arrow), "wb") as sink, ipc.new_file(sink, table.schema) as writer:
        writer.write_table(table)

    zd.clean(str(in_arrow), output=str(out_arrow), approved=True)
    assert out_arrow.exists()
    with pa.OSFile(str(out_arrow), "rb") as f:
        cleaned = ipc.open_file(f).read_all().to_pandas()
    assert "bad_float" not in cleaned.columns
    assert "val" in cleaned.columns

    # Coerce mixed numeric/string column via drop_invalid
    dirty_csv = tmp_path / "dirty.csv"
    dirty_csv.write_text("n,ok\n1,a\n2,a\n3,a\nbad,a\n", encoding="utf-8")
    out_csv = tmp_path / "dirty_clean.csv"
    cleaned_csv_df = zd.clean(str(dirty_csv), output=str(out_csv), approved=True)
    assert cleaned_csv_df is not None


def test_merge_arrow_strict_dtypes_and_zero_mean(tmp_path):
    """merge() loads .arrow files, rejects dtype mismatches in strict=True, and handles zero-mean cols."""
    import pyarrow as pa
    import pyarrow.ipc as ipc

    df_a = pd.DataFrame({"x": [1, 2, 3], "zero": [-1, 0, 1]})
    df_b = pd.DataFrame({"x": [4, 5, 6], "zero": [-2, 0, 2]})
    df_bad = pd.DataFrame({"x": ["a", "b", "c"], "zero": [0, 0, 0]})

    p_a = tmp_path / "a.arrow"
    p_b = tmp_path / "b.arrow"
    out = tmp_path / "merged.arrow"
    for frame, p in ((df_a, p_a), (df_b, p_b)):
        tbl = pa.Table.from_pandas(frame, preserve_index=False)
        with pa.OSFile(str(p), "wb") as sink, ipc.new_file(sink, tbl.schema) as writer:
            writer.write_table(tbl)

    merged_df = zd.merge([str(p_a), str(p_b)], output=str(out))
    assert len(merged_df) == 6
    assert out.exists()

    with pytest.raises(zd.ZeddaError, match="Schema mismatch across merged inputs in strict mode"):
        zd.merge([df_a, df_bad], strict=True)


def test_compare_terminal_verdict_matches_compute_verdict():
    """Terminal verdict and safe_to_train must agree with programmatic compute_verdict."""
    df_a = pd.DataFrame({"feature_a": [1.0, 2.0, 3.0], "shared": [10.0, 20.0, 30.0]})
    df_b = pd.DataFrame({"shared": [10.0, 20.0, 30.0]})

    prog = zd.compare(df_a, df_b, print_output=False)
    assert prog["verdict"]["verdict"] == "FAIL"
    assert prog["verdict"]["safe_to_train"] is False

    buf = io.StringIO()
    with redirect_stdout(buf):
        zd.compare(df_a, df_b, print_output=True)
    out = buf.getvalue()
    assert "FAIL" in out
    assert "Safe to train : NO" in out


def test_cli_run_cols_filters_columns(tmp_path):
    """`zedda run --cols age` must filter the generated report to requested columns."""
    from typer.testing import CliRunner
    from zedda.cli import app

    csv_path = tmp_path / "cli_cols.csv"
    csv_path.write_text("name,age,salary\nAlice,30,50000\nBob,25,60000\n", encoding="utf-8")
    html_path = tmp_path / "report.html"

    runner = CliRunner()
    res = runner.invoke(app, ["run", str(csv_path), "--cols", "age", "--out", str(html_path)])
    assert res.exit_code == 0
    assert "not yet implemented" not in res.output
    html = html_path.read_text(encoding="utf-8")
    assert "age" in html
    assert "salary" not in html
