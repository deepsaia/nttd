"""nttd result command -- show the scored, provenanced record of a run.

result.parquet is written when a session stops. It is what a leaderboard ingests
and what a verifier checks, so being able to read it directly is how an operator
confirms a run is complete and traceable before submitting it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from nttd.cli.helpers import console


def _sessions_dir() -> Path:
    return Path(os.environ.get("NTTD_SESSIONS_DIR", "logs/sessions"))


def result(
    session: Annotated[str, typer.Option("--session", "-s", help="Session ID")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit raw JSON rows")] = False,
) -> None:
    """Show the scored result record for a session.

    Examples:
      nttd result -s ses_20260803_120000_abcd1234
      nttd result -s ses_... --json > entry.json
    """
    from nttd.db.result_writer import read_result

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
    table = Table(title=f"Result: {session} ({first['score_version']})")
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
            str(row["primary_score"]) if row["rating_available"] else "[yellow]unrated[/]",
            f"{row['tiebreak_cargo']:,}",
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
        "scenario", f"{first['scenario_id'] or '?'} v{first['scenario_version'] or '?'}"
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
    provenance.add_row("scenario file", first["scenario_file_digest"] or "[yellow]none[/]")
    provenance.add_row("OpenTTD", first["openttd_version"] or "[yellow]unknown[/]")
    provenance.add_row("mode", first["runtime_mode"] or "?")
    provenance.add_row("end reason", first["end_reason"])
    provenance.add_row("game days", str(first["game_days"]))
    provenance.add_row("wall seconds", f"{first['wall_seconds']:.0f}")
    provenance.add_row("recorded at", str(first["recorded_at"]))
    console.print(provenance)

    # Flag what would block verification, so gaps are visible before submission.
    gaps: list[str] = []
    if not first["scored_session"]:
        gaps.append(
            "session was not scored -- operator powers were available throughout, "
            "so the run is not a benchmark result"
        )
    if not first["clean_run"]:
        gaps.append(
            f"{first['blocked_attempts']} operator operation(s) attempted and refused "
            f"({first['blocked_operations']}) -- nothing took effect, but the run is "
            f"not clean"
        )
    if seed < 0:
        gaps.append("no map seed -- the world cannot be regenerated")
    if not first["task_id"]:
        gaps.append("no task_id -- the run is not tied to a task instance")
    if first["nttd_git_dirty"]:
        gaps.append("uncommitted changes -- the recorded revision does not reproduce this run")
    if not first["gamescript_digest"]:
        gaps.append("GameScript not pinned")
    if any(r["cost_is_estimated"] for r in rows):
        gaps.append("token totals are partial (older cycles aged out of the buffer)")

    if gaps:
        console.print("\n[yellow]Verification gaps:[/]")
        for gap in gaps:
            console.print(f"  [yellow]-[/] {gap}")
    else:
        console.print("\n[green]Record is complete and verifiable.[/]")
