"""Agent performance report: per-agent metrics, success rates, and latency."""

from __future__ import annotations

from nttd.analysis.loader import SessionData
from nttd.analysis.plots import (
    agent_performance_bars,
    agent_success_rate_heatmap,
    cycle_decide_over_time,
    cycle_timing_boxplots,
)
from nttd.analysis.reports.registry import ReportResult, register


def _stats_from_cycles(session: SessionData) -> dict[str, dict]:
    """Compute per-agent stats from agent_cycles parquet data.

    Returns a dict keyed by agent_id with the same fields as agents.conf.
    Works for in-progress sessions where agents.conf has no stats yet.
    """
    df = session.agent_cycles
    if df.is_empty():
        return {}

    stats: dict[str, dict] = {}
    for group in df.partition_by("connection_id"):
        conn_id = group["connection_id"][0]
        # connection_id format: "session_id:company_id:agent_id"
        parts = str(conn_id).split(":")
        agent_id = parts[-1] if len(parts) >= 3 else str(conn_id)

        total_actions = int(group["actions_proposed"].sum())
        ok = int(group["actions_succeeded"].sum())
        failed = int(group["actions_failed"].sum())

        stats[agent_id] = {
            "total_cycles": len(group),
            "total_actions": total_actions,
            "successful_actions": ok,
            "failed_actions": failed,
            "avg_decide_ms": round(float(group["decide_ms"].mean()), 1),
            "avg_cycle_ms": round(float(group["total_ms"].mean()), 1),
        }
    return stats


@register("agent_performance")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce per-agent performance metrics and timing analysis."""
    data: dict = {"agents": []}
    md_lines: list[str] = ["# Agent Performance\n"]

    for s in sessions:
        # Compute live stats from agent_cycles (works for in-progress sessions)
        live_stats = _stats_from_cycles(s)

        for agent_id, info in s.agents.items():
            # Prefer live stats from parquet; fall back to agents.conf
            src = live_stats.get(agent_id, info)
            total = src.get("total_actions", 0)
            ok = src.get("successful_actions", 0)
            failed = src.get("failed_actions", 0)
            rate = round(ok / total * 100, 1) if total > 0 else 0.0

            agent_data = {
                "session_id": s.session_id,
                "agent_id": agent_id,
                "model": s.model,
                "total_actions": total,
                "successful_actions": ok,
                "failed_actions": failed,
                "success_rate": rate,
                "total_cycles": src.get("total_cycles", 0),
                "avg_decide_ms": round(src.get("avg_decide_ms", 0), 1),
                "avg_cycle_ms": round(src.get("avg_cycle_ms", 0), 1),
            }
            data["agents"].append(agent_data)

            md_lines.append(f"## {agent_id} ({s.model})")
            md_lines.append(f"- **Actions**: {total} total, {ok} ok, {failed} failed ({rate}%)")
            md_lines.append(f"- **Cycles**: {agent_data['total_cycles']}")
            md_lines.append(f"- **Avg decide**: {agent_data['avg_decide_ms']}ms")
            md_lines.append(f"- **Avg cycle**: {agent_data['avg_cycle_ms']}ms")
            md_lines.append("")

    figures = [
        ("agent_performance_bars", agent_performance_bars(sessions)),
        ("agent_success_heatmap", agent_success_rate_heatmap(sessions)),
        ("cycle_timing", cycle_timing_boxplots(sessions)),
        ("decide_latency", cycle_decide_over_time(sessions)),
    ]

    return ReportResult(
        name="agent_performance",
        title="Agent Performance",
        data=data,
        figures=figures,
        markdown="\n".join(md_lines),
    )
