"""``nttd submit`` -- package a finished session for submission."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from nttd.cli.helpers import console
from nttd.store import session_paths
from nttd.store.submission_bundle import MANIFEST_NAME, SubmissionBundle


def submit(
    session: Annotated[str, typer.Option("--session", "-s", help="Session ID")],
    no_archive: Annotated[
        bool, typer.Option("--no-archive", help="Write the directory but not the tarball")
    ] = False,
) -> None:
    """Package a session's artifacts and manifest into a submission bundle.

    nttd is self-hosted, so a submission cannot mean "we watched it happen". It means
    the artifacts are internally consistent and the score is recomputable. This
    assembles what makes that checkable: the result, the action log, the snapshots, the
    tile scan, the resolved scenario, and the savegame a verifier reloads.

    The manifest is a projection of the result record plus a digest per artifact, so it
    cannot contradict what was recorded. Run `nttd verify` on the bundle to check it
    yourself before submitting anywhere.

    Examples:
      nttd submit --session ses_abc123
      nttd submit -s ses_abc123 --no-archive
    """
    session_dir = session_paths.session_dir(session)
    if not session_dir.exists():
        console.print(f"[red]Session not found:[/] {session_dir}")
        raise typer.Exit(code=1)

    bundle = SubmissionBundle(session_dir)
    try:
        bundle_dir = bundle.build(archive=not no_archive)
    except FileNotFoundError as exc:
        console.print(f"[red]Cannot build a bundle:[/] {exc}")
        raise typer.Exit(code=1) from exc

    import json

    manifest = json.loads((bundle_dir / MANIFEST_NAME).read_text())
    _print_summary(manifest, bundle_dir)

    if not no_archive:
        archive = bundle.archive_path
        console.print(
            f"\nArchive: [cyan]{archive}[/] "
            f"({archive.stat().st_size / 1024:.0f} KB)"
        )

    gaps = manifest["verification_gaps"]
    if gaps:
        console.print("\n[yellow]This bundle cannot be fully verified:[/]")
        for gap in gaps:
            console.print(f"  [yellow]-[/] {gap}")
    else:
        console.print("\n[green]Nothing is missing: this bundle can be fully checked.[/]")


def _print_summary(manifest: dict, bundle_dir: object) -> None:
    """Show what went in, so a contestant sees the bundle rather than trusting it."""
    task = manifest["task"]
    world = manifest["world"]
    rules = manifest["rules"]

    table = Table(title=f"Submission: {manifest['session_id']}", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("task_id", task["task_id"] or "[yellow]none[/]")
    table.add_row("scenario", task["scenario_id"] or "?")
    table.add_row("map seed", str(task["map_seed"]))
    table.add_row("map digest", task["map_digest"] or "[yellow]no tile scan[/]")
    table.add_row(
        "world",
        f"{world['map_size_x']}x{world['map_size_y']} "
        f"{world['landscape']} {world['terrain_type']}",
    )
    table.add_row("profile", rules["profile_version"] or "?")
    table.add_row("scored", "yes" if rules["scored_session"] else "[yellow]no[/]")
    table.add_row("clean run", "yes" if rules["clean_run"] else "[yellow]no[/]")
    console.print(table)

    artifacts = Table(title="Artifacts", show_header=True)
    artifacts.add_column("File", style="bold")
    artifacts.add_column("Size", justify="right")
    artifacts.add_column("sha256")
    for name, meta in manifest["artifacts"].items():
        artifacts.add_row(name, f"{meta['bytes'] / 1024:.0f} KB", meta["sha256"] or "?")
    console.print(artifacts)
    console.print(f"Bundle: [cyan]{bundle_dir}[/]")
