"""
zedda CLI — EDA in one command
=================================

Usage::

    zedda run data.csv
    zedda run data.csv --ai
    zedda compare old.csv new.csv
    zedda info data.csv
"""

import os
import re
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

# SEC-P07: This sys.path insert allows running from source (development mode).
# It adds the parent 'python/' directory to the import path.
# Risk: if an attacker can write to this directory, they could shadow stdlib modules.
# This is acceptable for development but should be removed in production wheels.
_here = Path(__file__).parent.parent  # python/zedda/ -> python/
sys.path.insert(0, str(_here))

app = typer.Typer(
    name="zedda",
    help="⚡ EDA in one command — blazing fast, C++ powered",
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()


# ─────────────────────────────────────────────────────────────────
#  run — main command
#
#  zedda run data.csv
#  zedda run data.csv --ai
#  zedda run data.csv --cols age,salary
# ─────────────────────────────────────────────────────────────────
@app.command()
def run(
    path: str = typer.Argument(..., help="Path to CSV, Excel, JSON, or Parquet file"),
    ai: bool = typer.Option(
        False, "--ai", help="Add AI-generated insights (requires OPENAI_API_KEY)"
    ),
    cols: Optional[str] = typer.Option(
        None, "--cols", help="Comma-separated columns to profile"
    ),
    out: Optional[str] = typer.Option(None, "--out", help="Save report to HTML file"),
):
    """
    [bold green]Profile a data file[/bold green] and show EDA report.

    Examples::

        zedda run titanic.csv
        zedda run sales.xlsx --ai
        zedda run data.csv --out report.html
    """
    # Validate file exists
    if not Path(path).exists():
        console.print(f"[red]Error:[/red] File not found: {path}")
        raise typer.Exit(1)

    # Import here so CLI starts fast even if core is loading
    try:
        import zedda as zd
    except ImportError:
        console.print("[red]Error:[/red] zedda not installed correctly.")
        console.print("Run: [cyan]pip install zedda[/cyan]")
        raise typer.Exit(1)

    # Run profile
    try:
        result = zd.profile(path)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # AI insights
    if ai:
        _add_ai_insights(result)

    # Save HTML report
    if out:
        _save_html(result, out)
        file_uri = Path(out).resolve().as_uri()
        console.print(
            f"\n[green]Report saved:[/green] [link={file_uri}]{out}[/link] (Ctrl/Cmd + Click to open)"
        )


# ─────────────────────────────────────────────────────────────────
#  compare — diff two datasets
#
#  zedda compare train.csv test.csv
# ─────────────────────────────────────────────────────────────────
@app.command()
def compare(
    path_a: str = typer.Argument(..., help="First file"),
    path_b: str = typer.Argument(..., help="Second file"),
):
    """
    [bold green]Compare two datasets[/bold green] side by side.

    Shows schema diffs, null rate changes, and distribution shifts.

    Example::

        zedda compare train.csv test.csv
    """
    for p in [path_a, path_b]:
        if not Path(p).exists():
            console.print(f"[red]Error:[/red] File not found: {p}")
            raise typer.Exit(1)

    import zedda as zd

    zd.compare(path_a, path_b)


# ─────────────────────────────────────────────────────────────────
#  info — quick one-liner dataset info (no full EDA)
#
#  zedda info data.csv
# ─────────────────────────────────────────────────────────────────
@app.command()
def info(
    path: str = typer.Argument(..., help="Path to data file"),
):
    """
    [bold green]Quick info[/bold green] about a file — rows, cols, size.

    Faster than [cyan]run[/cyan] — no full stats computed.

    Example::

        zedda info data.csv
    """
    if not Path(path).exists():
        console.print(f"[red]Error:[/red] File not found: {path}")
        raise typer.Exit(1)

    p = Path(path)
    size_mb = p.stat().st_size / (1024 * 1024)

    console.print(
        Panel(
            f"[bold]File:[/bold]  {p.name}\n"
            f"[bold]Size:[/bold]  {size_mb:.2f} MB\n"
            f"[bold]Path:[/bold]  {p.resolve()}",
            title="[bold blue]File Info[/bold blue]",
            border_style="blue",
        )
    )

    # Quick row count
    console.print("[dim]Counting rows...[/dim]", end="\r")
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            rows = sum(1 for _ in f) - 1  # subtract header
        console.print(f"[bold]Rows:[/bold]  [green]{rows:,}[/green]          ")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────
#  version
# ─────────────────────────────────────────────────────────────────
@app.command()
def version():
    """Show zedda version."""
    import zedda

    console.print(f"zedda [bold cyan]{zedda.__version__}[/bold cyan]")


# ─────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────
def _add_ai_insights(result) -> None:
    """Call LLM API for dataset insights."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        console.print("\n[yellow]Tip:[/yellow] Set OPENAI_API_KEY for AI insights.")
        return

    try:
        from zedda.ai_insights import get_insights

        insights = get_insights(result)
        console.print(
            Panel(
                insights,
                title="[bold magenta]AI Insights[/bold magenta]",
                border_style="magenta",
            )
        )
    except Exception as e:
        error_msg = str(e)
        # SEC-P04: Redact API key patterns to prevent leaking secrets in terminal output
        error_msg = re.sub(r"sk-[A-Za-z0-9]{20,}", "sk-***REDACTED***", error_msg)
        console.print(f"[yellow]AI insights unavailable:[/yellow] {error_msg}")


def _save_html(result, out_path: str) -> None:
    """Save HTML report to file."""
    try:
        from zedda.report import render_html

        html = render_html(result)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        console.print(f"[yellow]HTML export unavailable:[/yellow] {e}")


# ─────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app()
