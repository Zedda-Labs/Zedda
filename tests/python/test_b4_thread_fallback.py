import pytest
import subprocess
import sys
import json
import zedda as zd


def test_single_thread_fallback_notice_captured(tmp_path, capfd):
    # 1. Clean file (no embedded newlines, size >= 16KB to trigger multithreading)
    clean_file = tmp_path / "clean_multithread.csv"
    lines = ["id,val\n"]
    for i in range(2500):
        lines.append(f"{i},data_{i}\n")
    clean_file.write_text("".join(lines), encoding="utf-8")
    assert clean_file.stat().st_size >= 16384

    # Run scan on clean file -> 0 fallback notices
    capfd.readouterr()  # clear buffer
    zd.scan(str(clean_file))
    captured = capfd.readouterr()
    assert (
        "[zedda info] Embedded newlines detected in quotes: falling back to single-threaded scan for correctness.\n"
        not in captured.err
    )

    # 2. File with embedded newline (size >= 16KB)
    fallback_file = tmp_path / "fallback_embedded.csv"
    lines = ["id,val\n", '1,"multi\nline"\n']
    for i in range(2, 2500):
        lines.append(f"{i},data_{i}\n")
    fallback_file.write_text("".join(lines), encoding="utf-8")
    assert fallback_file.stat().st_size >= 16384

    # Run scan on fallback file -> exactly 1 notice in stderr via capfd
    capfd.readouterr()  # clear buffer
    zd.scan(str(fallback_file))
    captured = capfd.readouterr()
    notice = "[zedda info] Embedded newlines detected in quotes: falling back to single-threaded scan for correctness.\n"
    assert captured.err.count(notice) == 1, (
        f"Expected notice count 1, got {captured.err.count(notice)}. Stderr: {captured.err}"
    )


def test_cli_scan_json_stdout_clean_with_stderr_notice(tmp_path):
    # Subprocess test for CLI: stderr notice must not pollute JSON stdout
    fallback_file = tmp_path / "cli_fallback.csv"
    lines = ["id,val\n", '1,"multi\nline"\n']
    for i in range(2, 2500):
        lines.append(f"{i},data_{i}\n")
    fallback_file.write_text("".join(lines), encoding="utf-8")

    cmd = [sys.executable, "-m", "zedda.cli", "scan", str(fallback_file), "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"CLI exited with {proc.returncode}: {proc.stderr}"

    # Stderr must contain the notice
    assert "[zedda info] Embedded newlines detected in quotes" in proc.stderr

    # Stdout must be clean, valid JSON
    data = json.loads(proc.stdout)
    assert "file_name" in data or "num_rows" in data
