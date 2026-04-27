"""Infrastructure report: build actions, stations, depots constructed."""

from __future__ import annotations

import json

import polars as pl

from nttd.analysis.loader import SessionData
from nttd.analysis.plots import actions_per_agent_bar, agent_spending_proxy
from nttd.analysis.reports.registry import ReportResult, register, session_header

_BUILD_ACTIONS = {
    "connect_road", "build_road_depot", "build_road_stop",
    "connect_rail", "build_rail_station", "build_rail_depot",
    "build_rail_signal", "build_rail_waypoint",
    "build_path", "build_canal", "build_lock", "build_buoy", "build_water_depot",
    "build_airport", "build_dock", "build_bridge", "build_tunnel",
}


def _compute_build_stats(s: SessionData) -> dict:
    """Count build actions by type and agent."""
    if s.actions.is_empty():
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    builds = s.actions.filter(pl.col("action_type").is_in(_BUILD_ACTIONS))
    ok = builds.filter(pl.col("status") == "success")

    vc_type = ok["action_type"].value_counts()
    by_type: dict[str, int] = dict(zip(vc_type["action_type"].to_list(), vc_type["count"].to_list()))
    vc_agent = ok["agent_id"].value_counts()
    by_agent: dict[str, int] = dict(zip(vc_agent["agent_id"].to_list(), vc_agent["count"].to_list()))

    # Extract station/depot counts from latest snapshot
    stations = 0
    try:
        last = s.snapshots.sort("game_date").row(-1, named=True)
        snap = json.loads(last["snapshot_json"])
        stations = len(snap.get("stations", []))
    except Exception:
        pass

    return {
        "session_id": s.session_id,
        "model": s.model,
        "has_data": True,
        "total_builds": len(ok),
        "failed_builds": len(builds) - len(ok),
        "builds_by_type": by_type,
        "builds_by_agent": by_agent,
        "stations_count": stations,
    }


@register("infrastructure")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce infrastructure build activity report."""
    stats = [_compute_build_stats(s) for s in sessions]
    data = {"infrastructure": stats}
    md_lines: list[str] = ["# Infrastructure Report\n"]

    for s, st in zip(sessions, stats):
        md_lines.append(session_header(s))
        if not st["has_data"]:
            md_lines.append("- No action data available\n")
            continue

        md_lines.append(f"- **Successful builds**: {st['total_builds']}")
        md_lines.append(f"- **Failed builds**: {st['failed_builds']}")
        md_lines.append(f"- **Stations**: {st['stations_count']}")
        md_lines.append("- **By type**:")
        for atype, count in sorted(st["builds_by_type"].items(), key=lambda x: -x[1]):
            md_lines.append(f"  - {atype}: {count}")
        md_lines.append("- **By agent**:")
        for agent, count in sorted(st["builds_by_agent"].items(), key=lambda x: -x[1]):
            md_lines.append(f"  - {agent}: {count}")
        md_lines.append("")

    figures = [
        ("actions_per_agent", actions_per_agent_bar(sessions)),
        ("agent_spending", agent_spending_proxy(sessions)),
    ]

    return ReportResult(
        name="infrastructure",
        title="Infrastructure Report",
        data=data,
        figures=figures,
        markdown="\n".join(md_lines),
    )
