"""nttd logs command — read or tail the JSONL event log."""

import time
from typing import Annotated, Optional

import typer

from nttd.cli.helpers import console, find_log, print_log_lines


def logs(
    run: Annotated[Optional[str], typer.Option("--run", "-r", help="Specific JSONL file")] = None,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Tail the newest log")] = False,
    log_dir: Annotated[str, typer.Option("--log-dir", help="Log directory")] = "runs",
    last: Annotated[int, typer.Option("--last", "-n", help="Show last N lines")] = 40,
) -> None:
    """Read or tail the JSONL event log."""
    log_path = find_log(run, log_dir)
    if log_path is None:
        console.print("[red]No log file found.[/]")
        raise typer.Exit(1)

    console.print(f"[dim]Reading {log_path}[/]")
    lines = log_path.read_text().strip().splitlines()
    print_log_lines(lines[-last:])

    if follow:
        console.print("[dim]Following (Ctrl-C to stop)…[/]")
        try:
            with log_path.open() as f:
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if line:
                        print_log_lines([line.strip()])
                    else:
                        time.sleep(0.5)
        except KeyboardInterrupt:
            pass
