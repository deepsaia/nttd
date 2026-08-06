"""``nttd actions`` -- show what a contestant can do, and what each action takes."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.table import Table

from nttd.cli.helpers import console
from nttd.config import action_manifest

_TIER_NOTE = {
    "participant": "",
    "operator": " [yellow](operator-tier: not available for play)[/]",
    "read_only": " [dim](read-only query)[/]",
}


def actions(
    action: Annotated[
        str | None,
        typer.Argument(help="Show one action's parameters instead of the whole list"),
    ] = None,
    category: Annotated[
        str | None, typer.Option("--category", "-c", help="Only this category")
    ] = None,
    playable: Annotated[
        bool,
        typer.Option("--playable", help="Only actions a contestant may submit"),
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the manifest as JSON")
    ] = False,
) -> None:
    """Show nttd's action surface, generated from the GameScript.

    This is the same description served at `/v1/public/actions` and handed to an MCP
    client, so what you read here is what an agent sees.

    Examples:
      nttd actions                        every action, by category
      nttd actions build_road_stop        one action's parameters
      nttd actions --category rail        one category
      nttd actions --playable --json      what a contestant may submit, as JSON
    """
    if action:
        _show_one(action, as_json)
        return

    entries = {
        name: entry
        for name, entry in action_manifest.ACTIONS.items()
        if (not category or entry["category"] == category)
        and (not playable or entry["tier"] == "participant")
    }
    if not entries:
        console.print(
            f"[yellow]No actions match.[/] "
            f"Categories: {', '.join(sorted({e['category'] for e in action_manifest.ACTIONS.values()}))}"
        )
        raise typer.Exit(code=1)

    if as_json:
        console.print_json(json.dumps({"actions": entries}))
        return

    _show_list(entries)


def _show_list(entries: dict) -> None:
    """One row per action, grouped by category."""
    by_category: dict[str, list[tuple[str, dict]]] = {}
    for name, entry in sorted(entries.items()):
        by_category.setdefault(entry["category"], []).append((name, entry))

    for category, rows in sorted(by_category.items()):
        table = Table(title=category, show_header=True)
        table.add_column("Action", style="bold")
        table.add_column("Parameters")
        table.add_column("Tier")
        for name, entry in rows:
            required = sorted(
                p for p, m in entry["parameters"].items() if m.get("required")
            )
            optional = sorted(
                p for p, m in entry["parameters"].items() if not m.get("required")
            )
            # No square brackets around the optional list: rich reads "[tile," as a
            # markup tag and silently swallows the rest, so actions with only
            # optional parameters rendered as taking none at all.
            parts = []
            if required:
                parts.append(", ".join(required))
            if optional:
                parts.append(f"[dim]opt: {', '.join(optional)}[/]")
            table.add_row(name, "  ".join(parts) or "[dim]none[/]", entry["tier"])
        console.print(table)

    console.print(
        f"\n{len(entries)} action(s). [dim]Required parameters first, then optional.[/]"
    )
    _describe_gaps(entries)


def _show_one(name: str, as_json: bool) -> None:
    """Everything known about one action."""
    entry = action_manifest.ACTIONS.get(name)
    if entry is None:
        console.print(f"[red]No such action:[/] {name}")
        console.print("[dim]Run `nttd actions` to see the list.[/]")
        raise typer.Exit(code=1)

    if as_json:
        console.print_json(json.dumps({name: entry}))
        return

    console.print(f"[bold]{name}[/]{_TIER_NOTE.get(entry['tier'], '')}")
    console.print(entry["description"] or "[yellow]No description yet.[/]")
    console.print(f"[dim]category: {entry['category']}  "
                  f"gamescript: {entry['gamescript_function']}[/]\n")

    if not entry["parameters"]:
        console.print("[dim]Takes no parameters.[/]")
        return

    table = Table(show_header=True)
    table.add_column("Parameter", style="bold")
    table.add_column("Required")
    table.add_column("Default")
    table.add_column("Description")
    for param, meta in sorted(entry["parameters"].items()):
        default = meta.get("default")
        rendered = "" if default is None and "default" not in meta else str(default)
        if meta.get("via") == "tile_resolver":
            rendered = "[dim]tile or x,y[/]"
        table.add_row(
            param,
            "yes" if meta.get("required") else "no",
            rendered,
            meta.get("description") or "[yellow]not described yet[/]",
        )
    console.print(table)


def _describe_gaps(entries: dict) -> None:
    """Say plainly how much of the surface is still undescribed.

    A silent gap reads as a complete manifest, and an agent composing actions from it
    would be working from names alone.
    """
    undescribed = [name for name, entry in entries.items() if not entry["description"]]
    if undescribed:
        console.print(
            f"[yellow]{len(undescribed)} of {len(entries)} have no description yet.[/] "
            f"[dim]Parameters and requiredness are generated from the GameScript and "
            f"are complete; the prose is written by hand.[/]"
        )
