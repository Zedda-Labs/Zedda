import pytest
import os
import tempfile
from pathlib import Path
import zedda as zd


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent.parent.parent / "fixtures" / "audit"


def test_report_generation(fixtures_dir):
    with tempfile.TemporaryDirectory() as td:
        out_file = os.path.join(td, "report.html")
        zd.report(str(fixtures_dir / "normal_business.csv"), out_file=out_file)

        assert os.path.exists(out_file)
        with open(out_file, encoding="utf-8") as f:
            html = f.read()

        assert "<html" in html
        assert "zedda report" in html
        assert "employee_id" in html


def test_report_xss_protection():
    import pandas as pd

    df = pd.DataFrame({"<script>alert(1)</script>": [1, 2, 3]})

    with tempfile.TemporaryDirectory() as td:
        out_file = os.path.join(td, "report.html")
        zd.report(df, out_file=out_file)

        with open(out_file, encoding="utf-8") as f:
            html = f.read()

        # The script tag should be escaped
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html or "&#x3C;script&#x3E;" in html


def test_export_alias(fixtures_dir):
    assert zd.export is zd.report

    with tempfile.TemporaryDirectory() as td:
        out_file = os.path.join(td, "report2.html")
        zd.export(str(fixtures_dir / "tiny.csv"), out_file=out_file)
        assert os.path.exists(out_file)
