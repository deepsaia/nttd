"""Evaluate one or more recorded NTTD runs."""

from pathlib import Path

import typer

from nttd.analysis.evaluation import evaluate as evaluate_runs
from nttd.analysis.evaluation import markdown_table


def evaluate(
    runs: list[str] = typer.Argument(..., help="Session/run paths. Use LABEL=PATH repeatedly to average seeds in one group."),
    output: Path = typer.Option(Path("evaluation"), "--output", "-o", help="Output directory."),
    company: int = typer.Option(0, "--company", help="Company ID to evaluate."),
    png: bool = typer.Option(False, "--png", help="Also export PNG (requires Chrome for Kaleido)."),
) -> None:
    """Write metrics, Pareto ranks and curves from recorded session files."""
    groups: dict[str, list[Path]] = {}
    for token in runs:
        label, separator, path = token.partition("=")
        if not separator:
            path, label = token, token
        if not label or not path:
            raise typer.BadParameter("Use PATH or LABEL=PATH")
        groups.setdefault(label, []).append(Path(path))
    try:
        table = evaluate_runs(groups, output, company_id=company, png=png)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(markdown_table(table))
    typer.echo(f"Evaluation written to {output.resolve()}")
