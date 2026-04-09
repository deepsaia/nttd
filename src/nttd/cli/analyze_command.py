"""nttd analyze command -- generate session analysis reports."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.markdown import Markdown
from rich.panel import Panel

from nttd.cli.helpers import complete_reports, console, resolve_session_path, session_option


def analyze(
    session: Annotated[str, session_option()],
    reports: Annotated[str, typer.Option(
        "--reports", "-r",
        help="Comma-separated report names, or 'all'",
        autocompletion=complete_reports,
    )] = "all",
    save: Annotated[
        Optional[str],
        typer.Option("--save", help="Save formats: markdown,png,html,json"),
    ] = None,
    output_dir: Annotated[
        Optional[str],
        typer.Option("--output-dir", "-o", help="Override save directory"),
    ] = None,
    compare: Annotated[
        Optional[str],
        typer.Option("--compare", help="Additional session IDs (comma-separated)"),
    ] = None,
    video_quality: Annotated[
        str,
        typer.Option("--video-quality", help="Video quality: low, medium, high", hidden=True),
    ] = "high",
    video_fps: Annotated[
        int,
        typer.Option("--video-fps", help="Video frames per second", hidden=True),
    ] = 4,
    video_max_frames: Annotated[
        int,
        typer.Option("--video-max-frames", help="Max video frames, 0=all", hidden=True),
    ] = 0,
    open_report: Annotated[bool, typer.Option("--open", help="Open markdown report after saving")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON to stdout instead of markdown")] = False,
) -> None:
    """Generate analysis reports for a session.

    By default, prints the report to the terminal. Use --save to write files.

    Examples:
      nttd analyze --session ses_abc123
      nttd analyze -s ses_abc123 --reports session_summary,financial
      nttd analyze -s ses_abc123 --save markdown,png
      nttd analyze -s ses_abc123 --json
      nttd analyze -s ses_abc123 --compare ses_def456,ses_ghi789
      nttd analyze -s ses_abc123 -r video --video-quality medium --video-fps 8
    """
    import json

    from nttd.analysis.loader import load_session
    from nttd.analysis.reports.registry import list_reports, run_reports
    from nttd.analysis.reports.renderer import render_all

    # Resolve session identifier (ID or path)
    session_id, session_dir = resolve_session_path(session)

    # Collect session IDs
    session_ids = [session]
    if compare:
        session_ids.extend(s.strip() for s in compare.split(",") if s.strip())

    # Load sessions
    with console.status(f"Loading {len(session_ids)} session(s)..."):
        sessions = []
        for sid in session_ids:
            sid_resolved, sid_dir = resolve_session_path(sid)
            try:
                sessions.append(load_session(sid_resolved, sessions_dir=sid_dir.parent))
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

    # Configure video report if requested
    if report_names is None or "video" in (report_names or []):
        from nttd.analysis.reports import video as video_mod
        video_mod.video_config["quality"] = video_quality
        video_mod.video_config["fps"] = video_fps
        video_mod.video_config["max_frames"] = video_max_frames

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

    # Show file artifacts (e.g. video) that were saved by report generators
    for r in results:
        for name, fpath in r.files:
            console.print(f"[green]{r.title}:[/] {fpath}")

    # Save to files (only if --save is specified)
    if save:
        if output_dir:
            out_path = Path(output_dir)
        else:
            out_path = session_dir / "reports"

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

