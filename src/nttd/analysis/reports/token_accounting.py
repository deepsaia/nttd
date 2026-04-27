"""Token accounting report: per-agent token usage, costs, and session totals."""

from __future__ import annotations

from nttd.analysis.loader import SessionData
from nttd.analysis.plots import token_usage_by_agent, tokens_over_time
from nttd.analysis.reports.registry import ReportResult, register


def _extract_agent_id(connection_id: str) -> str:
    parts = connection_id.split(":")
    return parts[-1] if len(parts) >= 3 else connection_id


def _get_col_or_default(group: object, col: str, default: str = "") -> str:
    """Safely get the first non-empty string value from a column."""
    if col not in group.columns:
        return default
    for val in group[col].to_list():
        if val and str(val).strip():
            return str(val)
    return default


@register("token_accounting")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce token usage breakdown per agent, per cycle, and session totals."""
    data: dict = {"per_agent": [], "session_totals": {}}
    md_lines: list[str] = ["# Token Accounting\n"]

    grand_prompt = 0
    grand_completion = 0
    grand_total = 0
    grand_cost = 0.0
    grand_cycles = 0
    has_token_data = False

    for s in sessions:
        df = s.agent_cycles
        if df.is_empty():
            continue

        has_tokens = "total_tokens" in df.columns
        if not has_tokens:
            continue

        if int(df["total_tokens"].sum()) == 0:
            continue
        has_token_data = True

        md_lines.append(f"## {s.name} ({s.model})\n")

        for group in df.partition_by("connection_id"):
            conn_id = str(group["connection_id"][0])
            agent_id = _extract_agent_id(conn_id)
            cycles = len(group)

            tp = int(group["prompt_tokens"].sum())
            tc = int(group["completion_tokens"].sum())
            tt = int(group["total_tokens"].sum())
            cost = round(float(group["total_cost"].sum()), 4)

            llm_model = _get_col_or_default(group, "llm_model")
            llm_provider = _get_col_or_default(group, "llm_provider")

            grand_prompt += tp
            grand_completion += tc
            grand_total += tt
            grand_cost += cost
            grand_cycles += cycles

            avg_prompt = round(tp / cycles) if cycles else 0
            avg_completion = round(tc / cycles) if cycles else 0
            avg_total = round(tt / cycles) if cycles else 0
            avg_cost = round(cost / cycles, 4) if cycles else 0.0

            agent_data = {
                "session_id": s.session_id,
                "agent_id": agent_id,
                "model": llm_model,
                "provider": llm_provider,
                "total_prompt_tokens": tp,
                "total_completion_tokens": tc,
                "total_tokens": tt,
                "total_cost": cost,
                "avg_prompt_per_cycle": avg_prompt,
                "avg_completion_per_cycle": avg_completion,
                "avg_total_per_cycle": avg_total,
                "avg_cost_per_cycle": avg_cost,
                "cycles": cycles,
            }
            data["per_agent"].append(agent_data)

            model_label = f"{llm_provider}/{llm_model}" if llm_provider and llm_model else ""
            md_lines.append(f"### {agent_id}")
            rows = [
                ("Model", model_label or "unknown"),
                ("Cycles", str(cycles)),
                ("Prompt tokens", f"{tp:,}"),
                ("Completion tokens", f"{tc:,}"),
                ("Total tokens", f"{tt:,}"),
                ("Cost", f"${cost:.4f}"),
                ("Avg prompt/cycle", f"{avg_prompt:,}"),
                ("Avg completion/cycle", f"{avg_completion:,}"),
                ("Avg total/cycle", f"{avg_total:,}"),
                ("Avg cost/cycle", f"${avg_cost:.4f}"),
            ]
            key_width = max(len(k) for k, _ in rows)
            for key, val in rows:
                md_lines.append(f"- **{key}**:{' ' * (key_width - len(key) + 1)}{val}")
            md_lines.append("")

    if not has_token_data:
        md_lines.append("No token data available for these sessions.\n")
        md_lines.append("Token tracking requires sessions recorded with nttd >= token accounting support.\n")

    grand_cost = round(grand_cost, 4)
    data["session_totals"] = {
        "prompt_tokens": grand_prompt,
        "completion_tokens": grand_completion,
        "total_tokens": grand_total,
        "total_cost": grand_cost,
        "total_cycles": grand_cycles,
    }

    if has_token_data:
        md_lines.append("## Session Totals\n")
        total_rows = [
            ("Total prompt tokens", f"{grand_prompt:,}"),
            ("Total completion tokens", f"{grand_completion:,}"),
            ("Total tokens", f"{grand_total:,}"),
            ("Total cost", f"${grand_cost:.4f}"),
            ("Total cycles", str(grand_cycles)),
        ]
        key_width = max(len(k) for k, _ in total_rows)
        for key, val in total_rows:
            md_lines.append(f"- **{key}**:{' ' * (key_width - len(key) + 1)}{val}")
        md_lines.append("")

    figures = [
        ("token_usage_by_agent", token_usage_by_agent(sessions)),
        ("tokens_over_time", tokens_over_time(sessions)),
    ]

    return ReportResult(
        name="token_accounting",
        title="Token Accounting",
        data=data,
        figures=figures,
        markdown="\n".join(md_lines),
    )
