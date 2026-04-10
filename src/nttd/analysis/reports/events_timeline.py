"""Events timeline report: chronological game events."""

from __future__ import annotations

from nttd.analysis.date_utils import game_date_to_str
from nttd.analysis.loader import SessionData
from nttd.analysis.plots import events_timeline
from nttd.analysis.reports.registry import ReportResult, register


@register("events_timeline")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce a chronological timeline of game events."""
    data: dict = {"events": []}
    md_lines: list[str] = ["# Events Timeline\n"]

    for s in sessions:
        if s.events.empty:
            md_lines.append(f"## {s.session_id} ({s.model})")
            md_lines.append("- No events recorded\n")
            continue

        events_sorted = s.events.sort_values("game_date")
        session_events: list[dict] = []

        md_lines.append(f"## {s.session_id} ({s.model})")
        md_lines.append(f"- **Total events**: {len(events_sorted)}\n")
        md_lines.append("| Date | Type | Company | Detail |")
        md_lines.append("|------|------|--------:|--------|")

        for _, row in events_sorted.iterrows():
            event = {
                "session_id": s.session_id,
                "game_date": int(row["game_date"]),
                "date_str": game_date_to_str(int(row["game_date"])),
                "event_type": row.get("event_type", ""),
                "company_id": int(row.get("company_id", -1)),
                "detail": row.get("detail", ""),
            }
            session_events.append(event)
            md_lines.append(
                f"| {event['date_str']} | {event['event_type']} "
                f"| {event['company_id']} | {event['detail']} |"
            )

        data["events"].extend(session_events)
        md_lines.append("")

    figures = [("events_timeline", events_timeline(sessions))]

    return ReportResult(
        name="events_timeline",
        title="Events Timeline",
        data=data,
        figures=figures,
        markdown="\n".join(md_lines),
    )
