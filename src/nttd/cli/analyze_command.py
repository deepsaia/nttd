"""nttd analyze command -- generate session analysis reports."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.markdown import Markdown
from rich.panel import Panel

from nttd.cli.helpers import console


def analyze(
    session_id: Annotated[str, typer.Argument(help="Session ID to analyze")],
    reports: Annotated[str, typer.Option("--reports", "-r", help="Comma-separated report names, or 'all'")] = "all",
    save: Annotated[
        Optional[str],
        typer.Option("--save", "-s", help="Save formats: markdown,png,html,json"),
    ] = None,
    output_dir: Annotated[
        Optional[str],
        typer.Option("--output-dir", "-o", help="Override save directory"),
    ] = None,
    video: Annotated[
        bool, typer.Option("--video/--no-video", help="Generate terrain video from snapshots"),
    ] = False,
    video_quality: Annotated[
        str,
        typer.Option("--video-quality", help="Video quality: low, medium, high"),
    ] = "high",
    video_fps: Annotated[
        int,
        typer.Option("--video-fps", help="Video frames per second"),
    ] = 4,
    video_max_frames: Annotated[
        int,
        typer.Option("--video-max-frames", help="Max frames (0 = all snapshots)"),
    ] = 0,
    compare: Annotated[
        Optional[str],
        typer.Option("--compare", help="Additional session IDs (comma-separated)"),
    ] = None,
    open_report: Annotated[bool, typer.Option("--open", help="Open markdown report after saving")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON to stdout instead of markdown")] = False,
) -> None:
    """Generate analysis reports for a session.

    By default, prints the report to the terminal. Use --save to write files.

    Examples:
      nttd analyze ses_abc123
      nttd analyze ses_abc123 --reports session_summary,financial
      nttd analyze ses_abc123 --save markdown,png
      nttd analyze ses_abc123 --save json --video
      nttd analyze ses_abc123 --json
      nttd analyze ses_abc123 --compare ses_def456,ses_ghi789
    """
    import json

    from nttd.analysis.loader import SESSIONS_DIR, load_session
    from nttd.analysis.reports.registry import list_reports, run_reports
    from nttd.analysis.reports.renderer import render_all

    # Collect session IDs
    session_ids = [session_id]
    if compare:
        session_ids.extend(s.strip() for s in compare.split(",") if s.strip())

    # Load sessions
    with console.status(f"Loading {len(session_ids)} session(s)..."):
        sessions = []
        for sid in session_ids:
            try:
                sessions.append(load_session(sid))
            except FileNotFoundError:
                console.print(f"[red]Session not found: {sid}[/]")
                raise typer.Exit(code=1)

    for s in sessions:
        status_label = "[yellow]IN PROGRESS[/]" if s.is_in_progress else f"[green]{s.status}[/]"
        console.print(
            f"  Loaded [cyan]{s.session_id}[/] ({s.model}) -- "
            f"{status_label} -- "
            f"{len(s.actions)} actions, {len(s.snapshots)} snapshots"
        )

    # Determine which reports to run
    report_names: list[str] | None = None
    if reports != "all":
        report_names = [r.strip() for r in reports.split(",") if r.strip()]
        available = list_reports()
        for name in report_names:
            if name not in available:
                console.print(f"[red]Unknown report: {name}[/]")
                console.print(f"Available: {', '.join(available)}")
                raise typer.Exit(code=1)

    # Run reports
    with console.status("Generating reports..."):
        results = run_reports(sessions, report_names)

    if not results:
        console.print("[yellow]No reports generated[/]")
        raise typer.Exit(code=1)

    console.print(f"  Generated {len(results)} report(s): {', '.join(r.name for r in results)}\n")

    # Print to terminal (default behavior)
    if json_output:
        payload = {
            "reports": [
                {"name": r.name, "title": r.title, "data": r.data}
                for r in results
            ]
        }
        console.print_json(json.dumps(payload, default=str))
    else:
        for r in results:
            if r.markdown:
                console.print(Panel(Markdown(r.markdown), title=r.title, border_style="cyan"))

    # Save to files (only if --save is specified)
    if save:
        if output_dir:
            out_path = Path(output_dir)
        else:
            out_path = SESSIONS_DIR / session_id / "reports"

        formats = [f.strip() for f in save.split(",") if f.strip()]
        with console.status("Saving outputs..."):
            written = render_all(results, out_path, formats)

        console.print(f"\n[green]Saved {len(written)} file(s) to {out_path}/[/]")
        for p in written:
            console.print(f"  {p.relative_to(out_path) if p.is_relative_to(out_path) else p}")

        if open_report:
            md_path = out_path / "report.md"
            if md_path.exists():
                subprocess.run([sys.executable, "-m", "webbrowser", str(md_path)], check=False)

    # Video generation
    if video:
        vid_out = Path(output_dir) if output_dir else SESSIONS_DIR / session_id / "reports"
        _generate_video(sessions[0], vid_out, video_quality, video_fps, video_max_frames)


def _generate_video(
    session: object,
    output_dir: Path,
    quality: str = "high",
    fps: int = 4,
    max_frames: int = 0,
) -> None:
    """Generate terrain-based video from session data."""
    try:
        from nttd.analysis.reports.video import generate_video

        sid = session.session_id if hasattr(session, "session_id") else "unknown"
        video_path = generate_video(
            session, output_dir / f"game_progression_{sid}.mp4",
            fps=fps, quality=quality, max_frames=max_frames,
        )
        console.print(f"[green]Video:[/] {video_path}")
    except ImportError:
        console.print("[yellow]Video generation requires imageio[pyav] -- skipping[/]")
    except FileNotFoundError as exc:
        console.print(f"[yellow]{exc}[/]")
