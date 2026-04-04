"""nttd tensorboard command — launch TensorBoard."""

import subprocess
from typing import Annotated

import typer

from nttd.cli.helpers import console


def tensorboard(
    log_dir: Annotated[str, typer.Option("--log-dir", help="TensorBoard log directory")] = "runs",
    port: Annotated[int, typer.Option("--port", "-p", help="TensorBoard port")] = 6006,
) -> None:
    """Launch TensorBoard pointing at the runs/ directory."""
    console.print(f"[bold]Launching TensorBoard[/] — open [cyan]http://localhost:{port}[/]")
    try:
        proc = subprocess.Popen(
            ["tensorboard", "--logdir", log_dir, "--port", str(port)],
        )
        proc.wait()
    except FileNotFoundError:
        console.print("[red]tensorboard not found.[/] Install with: [cyan]uv pip install tensorboard[/]")
        raise typer.Exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]TensorBoard stopped.[/]")
