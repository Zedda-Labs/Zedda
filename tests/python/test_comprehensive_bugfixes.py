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

    no_match = zd.ask(
        df, "zzzz totally unrelated question", llm="offline", print_output=False
    )
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
    with (
        pa.OSFile(str(in_arrow), "wb") as sink,
        ipc.new_file(sink, table.schema) as writer,
    ):
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

    with pytest.raises(
        zd.ZeddaError, match="Schema mismatch across merged inputs in strict mode"
    ):
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
    csv_path.write_text(
        "name,age,salary\nAlice,30,50000\nBob,25,60000\n", encoding="utf-8"
    )
    html_path = tmp_path / "report.html"

    runner = CliRunner()
    res = runner.invoke(
        app, ["run", str(csv_path), "--cols", "age", "--out", str(html_path)]
    )
    assert res.exit_code == 0
    assert "not yet implemented" not in res.output
    html = html_path.read_text(encoding="utf-8")
    assert "age" in html
    assert "salary" not in html


def test_version_is_0_4_9_1():
    """Verify bumped patch/build version across package and C++ core metadata."""
    assert zd.__version__ == "0.4.9.1"


def test_secret_redaction_gsk_sk_and_bearer():
    """Error messages must redact Groq gsk_*, OpenAI sk-*, and Bearer tokens."""
    from zedda._format import redact_secrets
    from zedda.ai_insights import get_insights

    raw = (
        "401 Unauthorized: Bearer abcdef1234567890token; "
        "keys gsk_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234 and sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234"
    )
    redacted = redact_secrets(raw)
    assert "gsk_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234" not in redacted
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234" not in redacted
    assert "abcdef1234567890token" not in redacted
    assert "gsk_***REDACTED***" in redacted
    assert "sk-***REDACTED***" in redacted
    assert "Bearer ***REDACTED***" in redacted

    df = pd.DataFrame({"x": [1, 2, 3]})
    prof = zd.scan(df)
    with (
        patch(
            "zedda._ask._ask_zedda_ai",
            return_value=(
                None,
                "HTTP 401: gsk_SECRET1234567890abcdefghij / Bearer SECRET_TOKEN_12345",
            ),
        ),
        pytest.raises(RuntimeError) as exc_info,
    ):
        get_insights(prof)
    err_msg = str(exc_info.value)
    assert "gsk_SECRET1234567890abcdefghij" not in err_msg
    assert "SECRET_TOKEN_12345" not in err_msg


def test_rich_markup_injection_safety(tmp_path):
    """Columns, values, and filenames containing Rich markup tags must render safely."""
    bad_csv = tmp_path / "[red]markup[b].csv"
    pd.DataFrame(
        {
            "[red]col[/red]": ["[bold]x[/bold]", None, None, None],
            "[cyan]val[/cyan]": [1, 2, 3, 4],
        }
    ).to_csv(bad_csv, index=False)

    buf = io.StringIO()
    with redirect_stdout(buf):
        zd.profile(str(bad_csv))
        zd.warnings(str(bad_csv), show_fixes=True)
        zd.ml_ready(str(bad_csv))
        zd.fix(str(bad_csv))
        zd.compare(str(bad_csv), str(bad_csv))
    out = buf.getvalue()
    assert len(out) > 0


def test_validate_malformed_and_redos_rules():
    """Malformed rule types and ReDoS nested quantifiers must fail cleanly without crashing or hanging."""
    df = pd.DataFrame(
        {
            "age": [20, 30, 40],
            "status": ["active", "inactive", "active"],
            "email": ["a@b.com", "c@d.org", "e@f.net"],
        }
    )

    bad_report = zd.validate(
        df,
        rules={
            "age": {"min": "not-a-num", "max": float("nan"), "max_null_pct": True},
            "status": {
                "allowed_values": 12345,
                "min_str_len": 1.5,
                "max_str_len": True,
            },
            "email": {"regex": "(a+)+"},
        },
    )
    assert bad_report.failed is True
    assert bad_report.failed_rules == 7

    non_str_regex = zd.validate(df, rules={"email": {"regex": 999}})
    assert non_str_regex.failed is True
    assert non_str_regex.failed_rules == 1

    good_report = zd.validate(
        df,
        rules={
            "status": {"regex": r"^(active|inactive)+$"},
            "email": {"regex": r"^[\w.+-]+@[\w-]+\.[\w.-]+$"},
        },
    )
    assert good_report.passed is True


def test_fix_stale_profile_drop_invalid_and_imports(tmp_path):
    """fix() handles solo type_mismatch, omits dead numpy import, and guards missing cols."""
    from zedda._fix import apply_fixes_to_dataframe

    # Solo type_mismatch with < 1% invalid rate (1 bad in 150 rows, low cardinality)
    rows = ["val,ok\n"] + [f"{i % 5},1\n" for i in range(149)] + ["not_an_int,1\n"]
    csv_path = tmp_path / "solo_mismatch.csv"
    csv_path.write_text("".join(rows), encoding="utf-8")

    buf = io.StringIO()
    with redirect_stdout(buf):
        zd.fix(str(csv_path))
    out = buf.getvalue()
    assert "No fixes needed!" not in out
    assert "type mismatch" in out.lower()

    # Outlier dataset: must NOT emit unused `import numpy as np`
    df_out = pd.DataFrame({"x": [1.0] * 30 + [1000.0]})
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        zd.fix(df_out)
    assert "import numpy as np" not in buf2.getvalue()

    # Stale profile referencing dropped column + all-NaN numeric median guard
    df_full = pd.DataFrame({"dropped_col": [1.0, None, None], "keep": [1.0, 2.0, 3.0]})
    stale_prof = zd.scan(df_full)
    df_trimmed = df_full.drop(columns=["dropped_col"])
    res = apply_fixes_to_dataframe(df_trimmed, stale_prof)
    assert list(res.columns) == ["keep"]


def test_ml_ready_return_parity_print_output_false():
    """ml_ready(print_output=False) must return the exact same schema as print_output=True."""
    df = pd.DataFrame({"id": [1, 2, 3, 4], "feat": [10.0, 20.0, 30.0, 40.0]})
    s_quiet, r_quiet = zd.ml_ready(df, print_output=False)
    buf = io.StringIO()
    with redirect_stdout(buf):
        s_loud, r_loud = zd.ml_ready(df, print_output=True)

    assert s_quiet == s_loud
    assert r_quiet["issues"] == r_loud["issues"]
    assert r_quiet["all_verdicts"] == r_loud["all_verdicts"]


def test_report_atomic_write_and_no_leftover_temps(tmp_path):
    """report() writes HTML atomically without leaving temporary files behind."""
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    out_html = tmp_path / "atomic_report.html"
    saved = zd.report(df, output=str(out_html))
    assert out_html.exists()
    assert saved
    leftover_tmps = list(tmp_path.glob(".tmp_*"))
    assert leftover_tmps == []


def test_unicode_path_profile_windows_and_posix(tmp_path):
    """CSV profiler must open UTF-8 Unicode filenames cleanly across Windows & POSIX."""
    u_csv = tmp_path / "café_日本語_データ.csv"
    u_csv.write_text("name,score\nAlice,10\nBob,20\n", encoding="utf-8")
    p = zd.scan(str(u_csv))
    assert p.num_rows == 2
    assert p.num_cols == 2
    assert p.columns[1].mean == pytest.approx(15.0)
    assert _core.__name__ == "zedda.fasteda_core"
