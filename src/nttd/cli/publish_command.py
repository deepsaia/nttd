"""``nttd publish`` -- file a finished bundle on the submissions dataset.

The third verb after `submit` and `verify`, and the last step a contestant owns. It opens
a pull request adding one bundle; it does not judge it.

**What deliberately is not here.** Verifying a submission and publishing a verdict live in
the board's own repository and run on infrastructure a contestant does not control. Shipping
the judge inside the thing being judged would undo the boundary the rest of nttd is careful
about, and would invite "I ran the board locally and it said verified". This command can put
a bundle in front of the board. Only the board decides what it is worth.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from nttd.cli.helpers import console
from nttd.store import session_paths
from nttd.store.submission_bundle import MANIFEST_NAME

# Where submissions live, and the shape of one path in it. Both are the board's to define;
# they are repeated here rather than imported because nttd does not depend on the board.
DATASET = "deepsai8/nttd-submissions"
SUBMISSIONS_ROOT = "submissions"

TOKEN_VAR = "HF_TOKEN"

# What an entrant is called when nothing can name them. Reached only by --dry-run, which
# does not read the token, so a dry run can show the shape of a path without one. A real
# filing always has a token, and a token always resolves to an account.
UNKNOWN_ENTRANT = "unknown-user"


def publish(
    bundle: Annotated[
        Path | None,
        typer.Option("--bundle", "-b", help="Bundle directory, from `nttd package`"),
    ] = None,
    session: Annotated[
        str | None,
        typer.Option("--session", "-s", help="Session id, to find its bundle"),
    ] = None,
    entrant: Annotated[
        str | None,
        typer.Option("--entrant", "-e", help="Your HuggingFace account. Read from the token if omitted"),
    ] = None,
    submission_id: Annotated[
        str | None,
        typer.Option("--id", help="Name for this entry. Defaults to the session id"),
    ] = None,
    dataset: Annotated[str, typer.Option("--dataset", help="Dataset to file against")] = DATASET,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Say what would be filed and stop")
    ] = False,
) -> None:
    """Open a pull request adding a submission bundle to the board's dataset.

    Run `nttd verify` on the bundle first. This command checks that a bundle is there and
    is whole; it does not re-check the run, and a bundle that fails verification can still
    be filed. That is deliberate: a self-reported score is published as one rather than
    hidden.

    Needs a HuggingFace token in the environment as HF_TOKEN, with write scope on your own
    account. The pull request is yours; nobody needs write access to the board.

    The entrant is read from that token unless you name one. It has to be your HuggingFace
    account: the board refuses a pull request that touches anything outside
    submissions/<the account that opened it>/, so a name that is merely a label is a
    submission that gets rejected.

    Examples:
      nttd publish -s 20260815-132431ist-quiet-pickle
      nttd publish -s 20260815-132431ist-quiet-pickle --entrant an-org-you-can-write-to
      nttd publish --bundle logs/sessions/<id>/submission --entrant ada --id air-01
    """
    directory = _bundle_dir(bundle, session)
    if not (directory / MANIFEST_NAME).exists():
        console.print(
            f"[red]{directory} is not a submission bundle: no {MANIFEST_NAME}.[/]\n"
            "Build one with `nttd package -s <session>` rather than assembling it by hand."
        )
        raise typer.Exit(code=1)

    token = os.environ.get(TOKEN_VAR)
    if not token and not dry_run:
        console.print(
            f"\n[red]No {TOKEN_VAR} in the environment.[/]\n"
            "A pull request is filed under your own account, so the token is yours and "
            "needs write scope on it. Create one at https://huggingface.co/settings/tokens"
        )
        raise typer.Exit(code=1)

    entrant = _entrant(entrant, token)
    name = submission_id or (session or directory.parent.name)
    target = f"{SUBMISSIONS_ROOT}/{entrant}/{name}"
    files = sorted(p for p in directory.iterdir() if p.is_file())

    console.print(f"Filing [bold]{directory}[/] as [bold]{target}[/] on {dataset}")
    for path in files:
        console.print(f"  {path.name}")

    if dry_run:
        console.print("\n[yellow]--dry-run: nothing was uploaded.[/]")
        return

    url = _upload(directory, files, target, dataset, token)
    console.print(f"\n[green]Filed.[/] {url}")
    console.print("The board verifies what was filed and publishes the verdict.")


def _entrant(supplied: str | None, token: str | None) -> str:
    """Whose submission this is, read from the token unless it was named.

    Not a label. The board's ingest checks the diff against the account that OPENED the pull
    request and refuses anything outside `submissions/<that account>/`, so an entrant that is
    not the HuggingFace username is not a cosmetic mismatch: the submission is rejected. A
    contestant had no way to know that from `--entrant`'s old description, "who is entering".

    Reading it from the token makes it right by construction. --entrant stays, because one
    account may file under an organisation it can write to, and because being unable to
    override a derived value is its own kind of trap.
    """
    if supplied:
        return supplied
    if not token:
        return UNKNOWN_ENTRANT

    try:
        who = _whoami_name(token)
    except Exception as failure:  # noqa: BLE001 - any failure here means "could not ask"
        console.print(f"[yellow]Could not read your account from {TOKEN_VAR}:[/] {failure}")
        return UNKNOWN_ENTRANT

    if not who:
        console.print(f"[yellow]{TOKEN_VAR} resolved to no account name.[/]")
        return UNKNOWN_ENTRANT

    console.print(f"Filing as [bold]{who}[/] [dim](read from {TOKEN_VAR})[/]")
    return who


def _whoami_name(token: str) -> str:
    """The account a token belongs to, as the hub reports it.

    Its own function so a test can replace it without a network, and so the failure handling
    around it stays readable.
    """
    from huggingface_hub import whoami  # noqa: PLC0415

    return str((whoami(token=token) or {}).get("name") or "")


def _bundle_dir(bundle: Path | None, session: str | None) -> Path:
    """The bundle to file, from either a path or a session id."""
    if bundle and session:
        console.print("[red]Give --bundle or --session, not both.[/]")
        raise typer.Exit(code=1)
    if bundle:
        return bundle
    if not session:
        console.print("[red]Give --bundle or --session.[/]")
        raise typer.Exit(code=1)
    return session_paths.session_dir(session) / "submission"


def _upload(
    directory: Path, files: list[Path], target: str, dataset: str, token: str
) -> str:
    """Upload the bundle as one pull request, and return its URL.

    One commit rather than a file at a time, so a reviewer sees a whole submission and a
    failure part way through leaves nothing half-filed.
    """
    try:
        from huggingface_hub import CommitOperationAdd, HfApi  # noqa: PLC0415
    except ImportError:
        console.print(
            "[red]Publishing needs huggingface_hub, which is an optional extra.[/]\n"
            "  uv sync --extra publish"
        )
        raise typer.Exit(code=1) from None

    operations = [
        CommitOperationAdd(path_in_repo=f"{target}/{path.name}", path_or_fileobj=str(path))
        for path in files
    ]
    commit = HfApi(token=token).create_commit(
        repo_id=dataset,
        repo_type="dataset",
        operations=operations,
        commit_message=f"submission: {target}",
        create_pr=True,
    )
    return str(getattr(commit, "pr_url", None) or getattr(commit, "commit_url", ""))
