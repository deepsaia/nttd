"""Session summary report: overview of configuration, duration, and agents."""

from __future__ import annotations

from nttd.analysis.loader import SessionData
from nttd.analysis.plots import session_overview_table
from nttd.analysis.reports.registry import ReportResult, register


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
            "total_cycles": len(s.agent_cycles),
            "total_snapshots": len(s.snapshots),
            "total_events": len(s.events),
            "agents": list(s.agents.keys()),
            "settings": s.settings,
        }
        data["sessions"].append(info)

        status_label = "IN PROGRESS" if s.is_in_progress else s.status.upper()
        md_lines.append(f"## {s.name} ({s.model})")
        md_lines.append(f"- **Status**: {status_label}")
        md_lines.append(f"- **Duration**: {info['duration_minutes']} min")
        md_lines.append(f"- **End reason**: {info['end_reason']}")
        md_lines.append(f"- **Actions**: {info['total_actions']}")
        md_lines.append(f"- **Cycles**: {info['total_cycles']}")
        md_lines.append(f"- **Snapshots**: {info['total_snapshots']}")
        md_lines.append(f"- **Events**: {info['total_events']}")
        md_lines.append(f"- **Agents**: {', '.join(info['agents'])}")
        md_lines.append("")

    figures = [("session_overview", session_overview_table(sessions))]

    return ReportResult(
        name="session_summary",
        title="Session Summary",
        data=data,
        figures=figures,
        markdown="\n".join(md_lines),
    )
