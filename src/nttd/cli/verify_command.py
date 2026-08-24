"""``nttd verify`` -- check a submission bundle yourself, before submitting it."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from nttd.cli.helpers import console
from nttd.schemas.verification import Verdict, VerificationReport
from nttd.store import session_paths
from nttd.store.submission_bundle import BUNDLE_DIR_NAME
from nttd.verify.validator import BundleValidator

_DEFAULT_BINARY = "/Applications/OpenTTD.app/Contents/MacOS/openttd"

_VERDICT_STYLE = {
    Verdict.VERIFIED: "green",
    Verdict.REPLAYED: "cyan",
    Verdict.UNVERIFIED: "yellow",
}

_VERDICT_MEANING = {
    Verdict.VERIFIED: "the score was recomputed from the save AND the world matches its seed",
    Verdict.REPLAYED: "the score was recomputed from the save; the world was not reconciled",
    Verdict.UNVERIFIED: "the artifacts do not support checking, so the score is self-reported",
}


def verify(
    bundle: Annotated[
        str | None,
        typer.Argument(help="Path to a submission bundle directory"),
    ] = None,
    session: Annotated[
        str | None,
        typer.Option("--session", "-s", help="Verify this session's bundle instead"),
    ] = None,
    regenerate: Annotated[
        bool,
        typer.Option(
            "--regenerate",
            help="Also regenerate the world from its seed (slower; required for 'verified')",
        ),
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the report as JSON")
    ] = False,
) -> None:
    """Check a submission bundle: a self-check, not an authoritative verdict.

    This runs on your machine, from code you could have changed, so the verdict it
    prints predicts what a leaderboard will conclude rather than granting anything. The
    verdict that counts is computed by the board's ingest, on infrastructure you do not
    control and with its own copy of nttd and the GameScript. Sharing the code is the
    point: you should be able to predict the outcome instead of being surprised by it.

    Nothing is written into the bundle. A bundle that carried its own verdict would be
    asserting something anyone could write.

    By default this checks the artifact digests, inspects the savegame, reloads it to
    recompute the score, and replays the action log -- seconds, and enough to earn
    'replayed'. `--regenerate` additionally rebuilds the world from its declared seed and
    compares terrain, which takes a map generation plus a full tile scan and is the only
    route to 'verified'.

    Examples:
      nttd verify -s ses_abc123
      nttd verify -s ses_abc123 --regenerate
      nttd verify logs/sessions/ses_abc123/submission --json
    """
    bundle_dir = _resolve(bundle, session)
    if bundle_dir is None:
        raise typer.Exit(code=1)

    validator = BundleValidator(
        bundle_dir=bundle_dir,
        openttd_binary=os.environ.get("NTTD_OPENTTD_BINARY", _DEFAULT_BINARY),
        base_config_dir=os.environ.get("NTTD_BASE_CONFIG") or None,
    )
    report = asyncio.run(validator.verify(regenerate=regenerate))

    if as_json:
        console.print_json(report.model_dump_json())
    else:
        _print(report, regenerate)

    # Non-zero only when the bundle cannot be checked at all, so this is usable as a
    # gate in a script without treating "replayed" as a failure.
    if report.verdict is Verdict.UNVERIFIED:
        raise typer.Exit(code=1)


def _resolve(bundle: str | None, session: str | None) -> Path | None:
    """Work out which directory to check, or complain usefully."""
    if bundle:
        path = Path(bundle)
        if (path / "manifest.json").exists():
            return path
        console.print(f"[red]No manifest.json in[/] {path}")
        return None

    if not session:
        console.print(
            "[red]Give a bundle path or --session.[/] "
            "Build one first with [cyan]nttd package -s <session>[/]."
        )
        return None

    path = session_paths.session_dir(session) / BUNDLE_DIR_NAME
    if not (path / "manifest.json").exists():
        console.print(
            f"[red]No bundle for {session}.[/] "
            f"Build one with [cyan]nttd package -s {session}[/]."
        )
        return None
    return path


def _print(report: VerificationReport, regenerate: bool) -> None:
    """Show each check, then the verdict and what it is worth."""
    table = Table(title=f"Self-check: {report.session_id or 'bundle'}")
    table.add_column("Check", style="bold")
    table.add_column("Result")
    table.add_column("Detail")

    for check in report.checks:
        if check.passed is True:
            mark = "[green]pass[/]"
        elif check.passed is False:
            mark = "[red]fail[/]"
        else:
            mark = "[dim]not run[/]"
        table.add_row(check.name, mark, check.detail)
    console.print(table)

    style = _VERDICT_STYLE[report.verdict]
    console.print(f"\nVerdict: [{style}]{report.verdict.value}[/]")
    console.print(f"  [dim]{_VERDICT_MEANING[report.verdict]}[/]")

    if report.verdict is Verdict.REPLAYED and not regenerate:
        console.print(
            "  [dim]Pass --regenerate to check the world against its seed, which is "
            "what earns 'verified'.[/]"
        )

    console.print(
        "\n[yellow]Advisory only.[/] This ran on your machine, from code you could "
        "have changed, so it predicts a board's verdict rather than granting one. "
        "The verdict that counts is computed by whoever ingests the bundle."
    )
