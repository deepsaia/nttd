"""Action analysis report: action type distribution, success/failure patterns."""

from __future__ import annotations

from nttd.analysis.loader import SessionData
from nttd.analysis.plots import (
    action_success_by_type,
    action_type_distribution,
    actions_per_cycle_scatter,
)
from nttd.analysis.reports.registry import ReportResult, register


def _compute_action_stats(s: SessionData) -> dict:
    """Compute per-action-type stats for a session."""
    if s.actions.empty:
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    total = len(s.actions)
    ok = int((s.actions["status"] == "success").sum())
    failed = total - ok
    rate = round(ok / total * 100, 1) if total > 0 else 0.0

    type_stats: list[dict] = []
    for action_type, group in s.actions.groupby("action_type"):
        t = len(group)
        s_ok = int((group["status"] == "success").sum())
        type_stats.append({
            "action_type": action_type,
            "total": t,
            "success": s_ok,
            "failed": t - s_ok,
            "success_rate": round(s_ok / t * 100, 1) if t > 0 else 0.0,
        })

    type_stats.sort(key=lambda x: x["total"], reverse=True)

    # Top failure reasons
    failures = s.actions[s.actions["status"] != "success"]
    error_counts: dict[str, int] = {}
    if "error" in failures.columns:
        for err in failures["error"].dropna():
            err_short = str(err)[:80]
            error_counts[err_short] = error_counts.get(err_short, 0) + 1

    top_errors = sorted(error_counts.items(), key=lambda x: -x[1])[:10]

    return {
        "session_id": s.session_id,
        "model": s.model,
        "has_data": True,
        "total_actions": total,
        "successful": ok,
        "failed": failed,
        "success_rate": rate,
        "by_type": type_stats,
        "top_errors": [{"error": e, "count": c} for e, c in top_errors],
    }


@register("action_analysis")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce action type distribution and failure pattern analysis."""
    stats = [_compute_action_stats(s) for s in sessions]
    data = {"actions": stats}
    md_lines: list[str] = ["# Action Analysis\n"]

    for st in stats:
        md_lines.append(f"## {st['session_id']} ({st['model']})")
        if not st["has_data"]:
            md_lines.append("- No action data available\n")
            continue

        md_lines.append(f"- **Total**: {st['total_actions']} ({st['success_rate']}% success)")
        md_lines.append(f"- **Success**: {st['successful']}, **Failed**: {st['failed']}\n")

        md_lines.append("### By Action Type")
        md_lines.append("| Type | Total | OK | Fail | Rate |")
        md_lines.append("|------|------:|---:|-----:|-----:|")
        for t in st["by_type"]:
            md_lines.append(
                f"| {t['action_type']} | {t['total']} | {t['success']} "
                f"| {t['failed']} | {t['success_rate']}% |"
            )

        if st["top_errors"]:
            md_lines.append("\n### Top Errors")
            md_lines.append("| Error | Count |")
            md_lines.append("|-------|------:|")
            for e in st["top_errors"]:
                md_lines.append(f"| {e['error']} | {e['count']} |")

        md_lines.append("")

    figures = [
        ("action_type_distribution", action_type_distribution(sessions)),
        ("action_success_by_type", action_success_by_type(sessions)),
        ("actions_per_cycle", actions_per_cycle_scatter(sessions)),
    ]

    return ReportResult(
        name="action_analysis",
        title="Action Analysis",
        data=data,
        figures=figures,
        markdown="\n".join(md_lines),
    )
