"""nttd scenario -- inspect and validate a scenario before running it.

Validation already produces good messages: profile deviations name the setting and
the value it is fixed at, and out-of-range choices list what is permitted. But the
only way to see them was to start a run, which spawns OpenTTD and generates a world
before the first check fails. For a T4 benchmark that is a long way to go to learn a
config has a typo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from nttd.cli.helpers import console, format_end_conditions_brief

scenario_app = typer.Typer(help="Inspect and validate scenario configs", no_args_is_help=True)


@scenario_app.command("validate")
def validate(
    config: Annotated[str, typer.Argument(help="Path to a HOCON scenario config")],
) -> None:
    """Check a scenario without starting anything.

    Runs the same strict validation a benchmark does, so what passes here is what a
    scored run will accept.

    Examples:
      nttd scenario validate config/benchmark/t2_example.conf
      nttd scenario validate my_variant.conf
    """
    from nttd.config.scenario_config import (
        ScenarioConfigError,
        load,
        scenario_to_settings,
    )

    path = Path(config)
    if not path.is_file():
        console.print(f"[red]No such config:[/] {config}")
        raise typer.Exit(code=1)

    cfg = load(path)
    try:
        settings = scenario_to_settings(cfg, strict=True)
    except ScenarioConfigError as exc:
        console.print(f"[red]Invalid:[/] {config}\n")
        # The exception packs every problem into one string so an author can fix a
        # config in a single pass; split it back out to read as a list. The leading
        # "N problem(s) ... (strict mode):" is a summary, not part of the first
        # problem, so it is shown separately rather than glued to it.
        raw = str(exc)
        _, _, joined = raw.partition("(strict mode): ")
        problems = (joined or raw).split("; ")
        for problem in problems:
            console.print(f"  [red]-[/] {problem}")
        console.print(f"\n[red]{len(problems)} problem(s).[/] Fix them and re-run.")
        raise typer.Exit(code=1) from exc

    scored = settings.get("_scored") == "1"
    table = Table(title=f"Valid: {cfg.name}", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("id", settings.get("_scenario_id", "?"))
    table.add_row(
        "scored",
        "[green]yes[/] (held to the benchmark profile)" if scored
        else "[yellow]no[/] (free play, nothing enforced)",
    )
    size_x = 2 ** int(settings.get("game_creation.map_x", "8"))
    size_y = 2 ** int(settings.get("game_creation.map_y", "8"))
    table.add_row(
        "world",
        f"{size_x}x{size_y} {settings.get('_dim_landscape', '?')} "
        f"{settings.get('_dim_terrain_type', '?')}",
    )
    seed = settings.get("_map_seed")
    table.add_row("seed", seed or "[yellow]none -- this run is not reproducible[/]")
    if scored:
        table.add_row("profile", settings.get("_profile_version", "?"))
    console.print(table)
    console.print(format_end_conditions_brief(cfg.end_conditions))

    if not seed:
        console.print(
            "\n[yellow]No map seed.[/] The world cannot be regenerated, so a result "
            "from this scenario cannot be checked. Set map.seed."
        )


@scenario_app.command("profile")
def show_profile() -> None:
    """Show the rules a scored scenario must satisfy.

    These come from config/benchmark/profile.conf, which is the single authority and
    is meant to be edited by hand. This prints what is actually in force, which is
    not always what a stale copy of the file says.

    Examples:
      nttd scenario profile
    """
    from nttd.config.benchmark_profile import active_profile

    profile = active_profile()

    if profile.source == "built-in fallback":
        console.print(
            "[yellow]Using built-in rules.[/] config/benchmark/profile.conf could "
            "not be read, so edits to it are having no effect.\n"
        )

    locked = Table(title="Locked (a scored scenario must match exactly)", show_header=False)
    locked.add_column("Setting", style="bold")
    locked.add_column("Value")
    for key, value in sorted(profile.locked.items()):
        locked.add_row(key, str(value))
    console.print(locked)

    allowed = Table(title="Free to vary (each is a leaderboard column)")
    allowed.add_column("Setting", style="bold")
    allowed.add_column("Permitted values")
    for key, values in sorted(profile.allowed.items()):
        allowed.add_row(key, ", ".join(str(v) for v in values))
    console.print(allowed)

    limits = Table(title="Fairness", show_header=False)
    limits.add_column("Setting", style="bold")
    limits.add_column("Value")
    for key, value in sorted(profile.fairness.items()):
        limits.add_row(key, str(int(value) if float(value).is_integer() else value))
    console.print(limits)

    console.print(
        f"\n[bold]profile version:[/] {profile.version}  "
        f"[dim](a digest of the rules above, recorded in every result)[/]\n"
        f"[bold]source:[/] {profile.source}"
    )

    if profile.scenario_allowlist:
        console.print(
            "\n[yellow]Scoring is restricted to a fixed slate:[/] "
            + ", ".join(profile.scenario_allowlist)
        )
    else:
        console.print(
            "\n[dim]Any scenario inside these rules may be scored. Conformance is "
            "the credential; there is no approved list.[/]"
        )
