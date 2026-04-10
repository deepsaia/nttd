"""Route completion funnel report: diagnose where agents get stuck in the
build-depot -> station -> vehicle -> orders -> start -> profit workflow."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from nttd.analysis.loader import SessionData
from nttd.analysis.reports.registry import ReportResult, register

# Action categories for funnel analysis
_INFRA_ACTIONS = {
    "connect_road", "connect_rail", "build_path",
    "build_canal", "build_lock", "build_buoy",
    "build_bridge", "build_tunnel",
}

_STATION_ACTIONS = {
    "build_rail_station", "build_road_stop", "build_dock", "build_airport",
}

_DEPOT_ACTIONS = {
    "build_road_depot", "build_rail_depot", "build_water_depot",
}

_VEHICLE_ACTIONS = {
    "buy_vehicle", "clone_vehicle",
}

_ORDER_ACTIONS = {
    "add_order", "insert_order", "set_order_flags",
    "share_orders", "copy_orders",
}

_START_ACTIONS = {
    "start_vehicle",
}

_ALL_OPERATION_ACTIONS = _VEHICLE_ACTIONS | _ORDER_ACTIONS | _START_ACTIONS

# Funnel stages in order
_FUNNEL_STAGES = [
    ("Infrastructure", _INFRA_ACTIONS),
    ("Stations", _STATION_ACTIONS),
    ("Depots", _DEPOT_ACTIONS),
    ("Buy vehicles", _VEHICLE_ACTIONS),
    ("Add orders", _ORDER_ACTIONS),
    ("Start vehicles", _START_ACTIONS),
]


def _compute_agent_funnel(
    actions: pd.DataFrame,
    agent_id: str,
) -> dict[str, Any]:
    """Compute route completion funnel for a single agent."""
    agent_actions = actions[actions["agent_id"] == agent_id]
    ok = agent_actions[agent_actions["status"] == "success"]
    failed = agent_actions[agent_actions["status"] != "success"]

    total = len(agent_actions)
    infra_count = len(agent_actions[agent_actions["action_type"].isin(
        _INFRA_ACTIONS | _STATION_ACTIONS | _DEPOT_ACTIONS
    )])
    ops_count = len(agent_actions[agent_actions["action_type"].isin(_ALL_OPERATION_ACTIONS)])

    # Funnel: did the agent successfully reach each stage?
    funnel: list[dict[str, Any]] = []
    for stage_name, stage_actions in _FUNNEL_STAGES:
        stage_all = agent_actions[agent_actions["action_type"].isin(stage_actions)]
        stage_ok = stage_all[stage_all["status"] == "success"]
        funnel.append({
            "stage": stage_name,
            "attempted": len(stage_all),
            "succeeded": len(stage_ok),
            "reached": len(stage_ok) > 0,
        })

    # Time-to-first for key milestones
    milestones: dict[str, int | None] = {}
    for stage_name, stage_actions in _FUNNEL_STAGES:
        stage_ok = ok[ok["action_type"].isin(stage_actions)]
        if not stage_ok.empty and "game_date" in stage_ok.columns:
            milestones[stage_name] = int(stage_ok["game_date"].min())
        else:
            milestones[stage_name] = None

    # Top errors for this agent
    agent_errors: list[dict[str, Any]] = []
    if "error" in failed.columns:
        err_counts: dict[str, int] = {}
        for err in failed["error"].dropna():
            err_short = str(err)[:100]
            err_counts[err_short] = err_counts.get(err_short, 0) + 1
        for err, count in sorted(err_counts.items(), key=lambda x: -x[1])[:5]:
            agent_errors.append({"error": err, "count": count})

    # Chronological action sequence (last 30 actions)
    recent = agent_actions.sort_values("game_date").tail(30)
    action_log: list[dict[str, str]] = []
    for _, row in recent.iterrows():
        action_log.append({
            "action_type": row["action_type"],
            "status": row["status"],
            "error": str(row.get("error", ""))[:60] if row.get("error") else "",
        })

    return {
        "agent_id": agent_id,
        "total_actions": total,
        "infrastructure_actions": infra_count,
        "operation_actions": ops_count,
        "infra_pct": round(infra_count / total * 100, 1) if total > 0 else 0.0,
        "ops_pct": round(ops_count / total * 100, 1) if total > 0 else 0.0,
        "funnel": funnel,
        "milestones": milestones,
        "top_errors": agent_errors,
        "recent_actions": action_log,
    }


def _compute_session_data(s: SessionData) -> dict[str, Any]:
    """Compute route completion stats for all agents in a session."""
    if s.actions.empty:
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    agent_ids = sorted(s.actions["agent_id"].unique())
    agent_funnels = [_compute_agent_funnel(s.actions, aid) for aid in agent_ids]

    # Vehicle profitability from latest snapshot (use total of both years)
    profitable_vehicles = 0
    total_vehicles = 0
    try:
        last = s.snapshots.sort_values("game_date").iloc[-1]
        snap = json.loads(last["snapshot_json"])
        vehicles = snap.get("vehicles", [])
        total_vehicles = len(vehicles)
        profitable_vehicles = sum(
            1 for v in vehicles
            if v.get("profit_this_year", 0) + v.get("profit_last_year", 0) > 0
        )
    except Exception:
        pass

    return {
        "session_id": s.session_id,
        "model": s.model,
        "has_data": True,
        "agents": agent_funnels,
        "total_vehicles": total_vehicles,
        "profitable_vehicles": profitable_vehicles,
    }


def _format_markdown(stats: list[dict[str, Any]]) -> str:
    """Render route completion stats as markdown."""
    lines: list[str] = ["# Route Completion Report\n"]

    for st in stats:
        lines.append(f"## {st['session_id']} ({st['model']})")
        if not st["has_data"]:
            lines.append("- No action data available\n")
            continue

        lines.append(
            f"- **Vehicles**: {st['total_vehicles']} total, "
            f"{st['profitable_vehicles']} profitable\n"
        )

        for agent in st["agents"]:
            aid = agent["agent_id"]
            lines.append(f"### {aid}")
            lines.append(
                f"- **Actions**: {agent['total_actions']} total "
                f"({agent['infra_pct']}% infrastructure, "
                f"{agent['ops_pct']}% operations)"
            )

            # Funnel table
            lines.append("\n**Route Completion Funnel**\n")
            lines.append("| Stage | Attempted | Succeeded | Reached |")
            lines.append("|-------|----------:|----------:|:-------:|")
            for stage in agent["funnel"]:
                reached = "YES" if stage["reached"] else "---"
                lines.append(
                    f"| {stage['stage']} | {stage['attempted']} "
                    f"| {stage['succeeded']} | {reached} |"
                )

            # Milestones
            milestone_parts: list[str] = []
            for stage_name, game_date in agent["milestones"].items():
                if game_date is not None:
                    milestone_parts.append(f"{stage_name}: day {game_date}")
            if milestone_parts:
                lines.append(f"\n**Milestones**: {', '.join(milestone_parts)}")

            # Top errors
            if agent["top_errors"]:
                lines.append("\n**Top Errors**\n")
                lines.append("| Error | Count |")
                lines.append("|-------|------:|")
                for e in agent["top_errors"]:
                    lines.append(f"| {e['error']} | {e['count']} |")

            # Recent action log
            lines.append("\n**Recent Actions** (last 30)\n")
            lines.append("| Action | Status | Error |")
            lines.append("|--------|--------|-------|")
            for a in agent["recent_actions"]:
                err = a["error"] if a["error"] else ""
                lines.append(f"| {a['action_type']} | {a['status']} | {err} |")

            lines.append("")

    return "\n".join(lines)


@register("route_completion")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce route completion funnel analysis per agent."""
    stats = [_compute_session_data(s) for s in sessions]
    data = {"route_completion": stats}
    markdown = _format_markdown(stats)

    return ReportResult(
        name="route_completion",
        title="Route Completion Report",
        data=data,
        figures=[],
        markdown=markdown,
    )
