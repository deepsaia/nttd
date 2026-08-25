"""nttd result command -- show the scored, provenanced record of a run.

result.parquet is written when a session stops. It is what a leaderboard ingests
and what a verifier checks, so being able to read it directly is how an operator
confirms a run is complete and traceable before submitting it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from nttd.cli.helpers import console
from nttd.store import session_paths
from nttd.store.verification_gaps import verification_gaps


def _print_model_breakdown(rows: list[dict]) -> None:
    """Show per-model tokens and cost, for the companies that reported any."""
    shown = False
    for row in rows:
        try:
            breakdown = json.loads(row.get("model_breakdown_json") or "[]")
        except json.JSONDecodeError:
            continue
        if not breakdown:
            continue
        table = Table(title=f"Reported spend: {row['company_name'] or row['company_id']}")
        table.add_column("Model")
        table.add_column("Role")
        table.add_column("Prompt", justify="right")
        table.add_column("Completion", justify="right")
        table.add_column("Cost", justify="right")
        for entry in breakdown:
            table.add_row(
                entry.get("model", "?"),
                entry.get("role", "") or "-",
                f"{entry.get('prompt_tokens', 0):,}",
                f"{entry.get('completion_tokens', 0):,}",
                # Blank when the price was never stated. A run whose tokens were counted
                # against a table with no entry for its model knows what it used and not
                # what it cost, and $0.0000 would answer a question nobody was asked.
                (
                    f"${entry['total_cost_usd']:.4f}"
                    if entry.get("total_cost_usd") is not None
                    else "[dim]not priced[/]"
                ),
            )
        console.print(table)
        shown = True
    if shown:
        console.print(
            "[dim]Contestant-reported and unverifiable: nttd runs no model, so it has "
            "no independent view of these. Action counts above are observed.[/]"
        )


def _sessions_dir() -> Path:
    return session_paths.sessions_dir()


def _format_metric(value: object, kind: str) -> str:
    """Render one metric, saying plainly when there is nothing to render."""
    if value is None:
        return "[dim]not recorded[/]"
    if kind == "bool":
        return "yes" if value else "no"
    if kind == "days":
        # -1 is the sentinel for never, which is not the same as day zero.
        return "[yellow]never[/]" if value == -1 else str(value)
    if kind == "usd":
        # Zero means spend was not reported. Rendering $0.00 would claim it was free.
        return "[dim]not reported[/]" if not value else f"${value:.4f}"
    if kind == "pct":
        return f"{float(value) * 100:.1f}%"
    if kind == "money":
        return f"{int(value):,}"
    if kind == "float":
        return f"{float(value):,.2f}"
    return str(value)


def result(
    session: Annotated[str, typer.Option("--session", "-s", help="Session ID")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit raw JSON rows")] = False,
) -> None:
    """Show the scored result record for a session.

    Examples:
      nttd result -s ses_20260803_120000_abcd1234
      nttd result -s ses_... --json > entry.json
    """
    from nttd.store.result_writer import read_result

    session_dir = _sessions_dir() / session
    rows = read_result(session_dir)
    if not rows:
        console.print(f"[red]No result record for[/] {session}")
        console.print(
            "result.parquet is written when the session stops. If the session is "
            "still running, stop it with [cyan]nttd session stop[/] first."
        )
        raise typer.Exit(code=1)

    if as_json:
        # default=str so the recorded_at timestamp survives serialisation.
        console.print_json(json.dumps(rows, default=str))
        return

    first = rows[0]
    table = Table(title=f"Result: {session}")
    table.add_column("Rank", justify="right")
    table.add_column("Company")
    table.add_column("Score", justify="right")
    table.add_column("Cargo", justify="right")
    table.add_column("Value", justify="right")
    table.add_column("Actions", justify="right")
    table.add_column("Model")
    table.add_column("Cost", justify="right")

    for rank, row in enumerate(rows, 1):
        actions = row["total_actions"]
        ok = row["successful_actions"]
        table.add_row(
            str(rank),
            row["company_name"] or str(row["company_id"]),
            str(row["performance_rating"]) if row["performance_rating"] >= 0
            else "[yellow]unrated[/]",
            f"{row['total_cargo']:,}",
            f"{row['company_value']:,}",
            f"{ok}/{actions}" if actions else "-",
            row["model"] or "-",
            f"${row['total_cost_usd']:.2f}" if row["total_cost_usd"] else "-",
        )
    console.print(table)

    seed = first["map_seed"]
    provenance = Table(title="Provenance", show_header=False)
    provenance.add_column("Field", style="bold")
    provenance.add_column("Value")
    provenance.add_row(
        "scored session",
        "[green]yes[/]" if first["scored_session"] else "[yellow]no (unscored)[/]",
    )
    provenance.add_row(
        "clean run",
        "[green]yes[/]" if first["clean_run"]
        else f"[red]no[/] ({first['blocked_attempts']} blocked: {first['blocked_operations']})",
    )
    provenance.add_row("capability set", first["capability_digest"] or "[yellow]none[/]")
    provenance.add_row("task_id", first["task_id"] or "[yellow]none[/]")
    provenance.add_row(
        "scenario", str(first["scenario_id"] or "?")
    )
    provenance.add_row("map seed", str(seed) if seed >= 0 else "[yellow]random[/]")
    # The dimensions a scored scenario may vary. Shown because a reader comparing
    # two results needs them: they are permitted to differ only on being disclosed.
    if first["map_size_x"]:
        provenance.add_row(
            "world",
            f"{first['map_size_x']}x{first['map_size_y']} {first['landscape']} "
            f"{first['terrain_type']}"
            + (f" (profile v{first['profile_version']})" if first["profile_version"] else ""),
        )
    provenance.add_row("settings digest", first["settings_digest"] or "[yellow]none[/]")
    provenance.add_row(
        "nttd revision",
        (first["nttd_git_sha"] or "?")
        + (" [yellow](uncommitted changes)[/]" if first["nttd_git_dirty"] else ""),
    )
    provenance.add_row("GameScript", first["gamescript_digest"] or "[yellow]none[/]")
    save_digest = first["final_save_digest"]
    provenance.add_row(
        "final save",
        f"{save_digest} ({first['final_save_bytes'] / 1024:.0f} KB)" if save_digest
        else "[yellow]none -- the score cannot be recomputed[/]",
    )
    provenance.add_row("scenario file", first["scenario_file_digest"] or "[yellow]none[/]")
    provenance.add_row("OpenTTD", first["openttd_version"] or "[yellow]unknown[/]")
    provenance.add_row("mode", first["runtime_mode"] or "?")
    provenance.add_row("end reason", first["end_reason"])
    provenance.add_row("game days", str(first["game_days"]))
    provenance.add_row("wall seconds", f"{first['wall_seconds']:.0f}")
    provenance.add_row("recorded at", str(first["recorded_at"]))
    console.print(provenance)

    # Per-model spend, when reported. Shown as a table rather than folded into the
    # single cost figure because a multi-agent system routinely runs several models,
    # and a cheap router in front of one expensive planner is a different system from
    # the same total spent uniformly.
    _print_model_breakdown(rows)

    # Flag what would block verification, so gaps are visible before submission.
    # Derived in store/verification_gaps.py so a submission bundle records the same
    # list rather than a second implementation of it.
    gaps = verification_gaps(rows)

    if gaps:
        console.print("\n[yellow]Verification gaps:[/]")
        for gap in gaps:
            console.print(f"  [yellow]-[/] {gap}")
    else:
        console.print("\n[green]Record is complete and verifiable.[/]")
