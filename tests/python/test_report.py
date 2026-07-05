import os

import pandas as pd
import pytest
import zedda as zd


@pytest.fixture
def sample_csv(tmp_path):
    df = pd.DataFrame(
        {
            "id": range(100),
            "value": [i * 1.5 for i in range(100)],
            "category": ["A", "B", "C", "D"] * 25,
            "<script>alert(1)</script>": [0] * 100,  # Malicious column name test
        }
    )
    path = tmp_path / "test_data.csv"
    df.to_csv(path, index=False)
    return str(path)


def test_report_default_path(sample_csv, monkeypatch, tmp_path):
    """Test generating a report to the default path."""
    # Change into tmp_path so the default output is generated there
    monkeypatch.chdir(tmp_path)
    out_path = zd.report(sample_csv)

    assert os.path.exists(out_path)
    assert out_path.endswith("test_data_report.html")

    with open(out_path, encoding="utf-8") as f:
        html = f.read()

    assert "<html" in html
    assert "test_data.csv" in html


def test_report_custom_path(sample_csv, tmp_path):
    """Test generating a report to a specific custom path."""
    out_path = str(tmp_path / "my_custom_report.html")
    res = zd.report(sample_csv, output=out_path)

    assert res == os.path.abspath(out_path)
    assert os.path.exists(out_path)


def test_report_dataframe_input(tmp_path):
    """Test generating a report directly from a DataFrame."""
    df = pd.DataFrame({"A": [1, 2, 3], "B": ["x", "y", "z"]})

    out_path = str(tmp_path / "df_report.html")
    zd.report(df, output=out_path)

    assert os.path.exists(out_path)
    with open(out_path, encoding="utf-8") as f:
        html = f.read()
    assert "&lt;DataFrame&gt;" in html


def test_report_no_external_urls(sample_csv, tmp_path):
    """Verify true offline self-containment (zero external CDNs)."""
    out_path = str(tmp_path / "offline.html")
    zd.report(sample_csv, output=out_path)

    with open(out_path, encoding="utf-8") as f:
        html = f.read()

    # There should be no src="http..." or href="http..." linking to external assets
    # (The only external link allowed is the GitHub link in the footer, which is an <a> tag, not an asset load)
    assert 'src="http' not in html
    assert "src='http" not in html
    assert '<link href="http' not in html
    assert "Plotly" not in html
    assert "Chart.js" not in html


def test_report_xss_prevention(sample_csv, tmp_path):
    """Verify dynamic values like column names are properly HTML escaped."""
    out_path = str(tmp_path / "xss.html")
    zd.report(sample_csv, output=out_path)

    with open(out_path, encoding="utf-8") as f:
        html = f.read()

    # The raw script tag should NOT be present
    assert "<script>alert(1)</script>" not in html
    # But the escaped version should be present
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_titanic_file_size(tmp_path):
    """Verify the generated report size remains under 500KB for typical datasets."""
    titanic_path = "Titanic-Dataset.csv"
    if not os.path.exists(titanic_path):
        pytest.skip("Titanic-Dataset.csv not found in working directory")

    out_path = str(tmp_path / "titanic_report.html")
    zd.report(titanic_path, output=out_path)

    size_bytes = os.path.getsize(out_path)
    size_kb = size_bytes / 1024

    assert size_kb < 500, f"Report size too large: {size_kb:.1f} KB"
