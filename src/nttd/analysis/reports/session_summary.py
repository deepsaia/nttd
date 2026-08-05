"""Session summary report: overview of configuration, duration, and agents."""

from __future__ import annotations

from nttd.analysis.loader import SessionData
from nttd.analysis.plots import session_overview_table
from nttd.analysis.reports.registry import ReportResult, register, session_header


@register("session_summary")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce a summary of session config, duration, agents, and status."""
    data: dict = {"sessions": []}
    md_lines: list[str] = ["# Session Summary\n"]

    for s in sessions:
        info = {
            "session_id": s.session_id,
            "name": s.name,
            "model": s.model,
            "status": s.status,
            "duration_minutes": round(s.duration_minutes, 1),
            "end_reason": s.end_reason or "manual",
            "created_at": s.created_at,
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "is_in_progress": s.is_in_progress,
            "total_actions": len(s.actions),
            "total_snapshots": len(s.snapshots),
            "total_events": len(s.events),
            "agents": list(s.agents.keys()),
            "settings": s.settings,
        }
        data["sessions"].append(info)

        status_label = "IN PROGRESS" if s.is_in_progress else s.status.upper()
        dur_total_sec = int(info["duration_minutes"] * 60)
        dur_h, dur_rem = divmod(dur_total_sec, 3600)
        dur_m, dur_s = divmod(dur_rem, 60)
        dur_str = f"{dur_h:02d}:{dur_m:02d}:{dur_s:02d}"

        md_lines.append(session_header(s))
        rows = [
            ("Status", status_label),
            ("Duration (hh:mm:ss)", dur_str),
            ("End reason", info["end_reason"]),
            ("Actions", str(info["total_actions"])),
            ("Snapshots", str(info["total_snapshots"])),
            ("Events", str(info["total_events"])),
            ("Agents", ", ".join(info["agents"])),
        ]
        key_width = max(len(k) for k, _ in rows)
        for key, val in rows:
            md_lines.append(f"- **{key}**:{' ' * (key_width - len(key) + 1)}{val}")
        md_lines.append("")

    figures = [("session_overview", session_overview_table(sessions))]

    return ReportResult(
        name="session_summary",
        title="Session Summary",
        data=data,
        figures=figures,
        markdown="\n".join(md_lines),
    )
