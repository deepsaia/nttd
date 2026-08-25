"""nttd runex command -- hand over to the interactive experiment launcher.

The launcher lives in nttd-workbench, not here, and that is deliberate. nttd is the engine and
the referee: it stands up a world, takes actions and scores what happened. It runs no agent, and
a contestant does not need it installed to write one. Owning the thing that starts agents would
make that claim false.

So this is a doorway rather than an implementation. It exists because `nttd runex` is the name a
contestant reaches for once they already have the nttd command in their hand, and because the
alternative to a doorway is a contestant discovering by trial that the two repositories exist.
"""

from typing import Annotated

import typer

from nttd.cli.helpers import console

_MISSING = """[yellow]The experiment launcher is not installed.[/]

It lives in the workbench, a separate repository so that nttd itself stays free of any
framework:

    git clone https://github.com/deepsaia/nttd-workbench
    cd nttd-workbench
    uv sync

then run it from there with [cyan]uv run runex[/] or [cyan]python -m runex[/]."""


def runex(
    ctx: Annotated[typer.Context, typer.Option()],
) -> None:
    """Run an experiment against a live session, choosing interactively.

    Everything after `runex` is passed through, so `nttd runex --help` is the launcher's
    own help rather than this one.

    Examples:
      nttd runex
      nttd runex --kind neuro-san
    """
    try:
        from runex.cli import app  # noqa: PLC0415
    except ImportError:
        console.print(_MISSING)
        raise typer.Exit(code=1) from None

    app(args=ctx.args, prog_name="nttd runex", standalone_mode=True)
