"""Reusable plot functions for nttd session analysis.

All functions take DataFrames or SessionData objects and return plotly Figures.
Call fig.show() to display interactively, or fig.write_image("path.png") to save.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from nttd.analysis.date_utils import game_date_to_str

if TYPE_CHECKING:
    from nttd.analysis.loader import SessionData

# Consistent color palette
AGENT_COLORS = {
    "road-agent": "#4C78A8",
    "rail-agent": "#F58518",
    "air-agent": "#E45756",
    "water-agent": "#72B7B2",
}

MODEL_COLORS = {
    "gpt-4.1-mini": "#636EFA",
    "gpt-5.2": "#EF553B",
}

_TEMPLATE = "plotly_white"


def _short_label(s: SessionData) -> str:
    """Short label for legends -- just the model name."""
    return s.model


def _date_tickvals(game_dates: pd.Series, n_ticks: int = 8) -> tuple[list, list]:
    """Generate evenly spaced tick values and human-readable tick labels."""
    mn, mx = game_dates.min(), game_dates.max()
    step = max(1, (mx - mn) // (n_ticks - 1))
    vals = list(range(mn, mx + 1, step))
    labels = [game_date_to_str(v) for v in vals]
    return vals, labels


def _apply_date_xaxis(fig: go.Figure, game_dates: pd.Series, row: int | None = None, col: int | None = None) -> None:
    """Apply human-readable date ticks to x-axis."""
    vals, labels = _date_tickvals(game_dates)
    kwargs: dict = dict(tickvals=vals, ticktext=labels, tickangle=-30)
    if row is not None and col is not None:
        fig.update_xaxes(**kwargs, row=row, col=col)
    else:
        fig.update_xaxes(**kwargs)


def _all_game_dates(sessions: list[SessionData]) -> pd.Series:
    """Concatenate game_date columns from all sessions."""
    parts = [s.snapshots["game_date"] for s in sessions if not s.snapshots.empty]
    if not parts:
        return pd.Series(dtype=int)
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------------------
# Session overview
# ---------------------------------------------------------------------------

def session_overview_table(sessions: list[SessionData]) -> go.Figure:
    """Summary table comparing session configs and outcomes."""
    headers = ["Metric", *[_short_label(s) for s in sessions]]
    fields = [
        ("Session ID", [s.session_id for s in sessions]),
        ("Model", [s.model for s in sessions]),
        ("Duration (min)", [f"{s.duration_minutes:.1f}" for s in sessions]),
        ("End Reason", [s.end_reason or "manual" for s in sessions]),
        ("Total Actions", [str(len(s.actions)) for s in sessions]),
        ("Total Cycles", [str(len(s.agent_cycles)) for s in sessions]),
        ("Snapshots", [str(len(s.snapshots)) for s in sessions]),
        ("Agents", [str(len(s.agents)) for s in sessions]),
    ]
    cells_values = [[f[0] for f in fields]] + [list(col) for col in zip(*[f[1] for f in fields])]

    fig = go.Figure(data=[go.Table(
        header=dict(values=headers, fill_color="#2D3748", font=dict(color="white", size=13), align="left"),
        cells=dict(values=cells_values, fill_color=[["#F7FAFC"] * len(fields)] * len(headers), align="left"),
    )])
    fig.update_layout(title="Session Overview", height=350, margin=dict(t=40, b=10))
    return fig


# ---------------------------------------------------------------------------
# Agent performance
# ---------------------------------------------------------------------------

def agent_performance_bars(sessions: list[SessionData]) -> go.Figure:
    """Grouped bar chart: success rate, actions, cycles, latency per agent."""
    rows = []
    for s in sessions:
        for agent_id, info in s.agents.items():
            total = info.get("total_actions", 0)
            ok = info.get("successful_actions", 0)
            rows.append({
                "agent": agent_id,
                "model": s.model,
                "total_actions": total,
                "successful": ok,
                "failed": info.get("failed_actions", 0),
                "success_rate": ok / total * 100 if total > 0 else 0,
                "cycles": info.get("total_cycles", 0),
                "avg_decide_ms": info.get("avg_decide_ms", 0),
            })

    df = pd.DataFrame(rows)

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=("Success Rate (%)", "Total Actions", "Total Cycles", "Avg Decide Latency (ms)"),
        vertical_spacing=0.18, horizontal_spacing=0.12,
    )

    for i, metric in enumerate(["success_rate", "total_actions", "cycles", "avg_decide_ms"]):
        row, col = divmod(i, 2)
        for model in df["model"].unique():
            mdf = df[df["model"] == model]
            fig.add_trace(go.Bar(
                x=mdf["agent"], y=mdf[metric],
                name=model,
                marker_color=MODEL_COLORS.get(model, "#999"),
                showlegend=(i == 0),
            ), row=row + 1, col=col + 1)

    fig.update_layout(
        title="Agent Performance: Model Comparison",
        barmode="group", template=_TEMPLATE,
        height=650, legend=dict(orientation="h", y=1.06),
    )
    return fig


def agent_success_rate_heatmap(sessions: list[SessionData]) -> go.Figure:
    """Heatmap of action success rates by agent and model."""
    rows = []
    for s in sessions:
        for agent_id, info in s.agents.items():
            total = info.get("total_actions", 0)
            ok = info.get("successful_actions", 0)
            rows.append({
                "agent": agent_id,
                "model": s.model,
                "success_rate": ok / total * 100 if total > 0 else 0,
            })

    df = pd.DataFrame(rows)
    pivot = df.pivot(index="agent", columns="model", values="success_rate")

    fig = px.imshow(
        pivot, text_auto=".1f", color_continuous_scale="RdYlGn",
        zmin=0, zmax=100,
        labels=dict(x="Model", y="Agent", color="Success %"),
        title="Action Success Rate by Agent and Model",
    )
    fig.update_layout(template=_TEMPLATE, height=350, margin=dict(l=120))
    return fig


# ---------------------------------------------------------------------------
# Financial time-series
# ---------------------------------------------------------------------------

def company_finances_timeseries(sessions: list[SessionData]) -> go.Figure:
    """Line chart of company 0 balance, income, and value over game date."""
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        subplot_titles=("Balance", "Income", "Company Value"),
        vertical_spacing=0.08,
    )

    all_dates = _all_game_dates(sessions)
    for s in sessions:
        if s.snapshots.empty:
            continue
        df = s.snapshots.sort_values("game_date")
        color = MODEL_COLORS.get(s.model, "#999")
        label = _short_label(s)

        for i, col in enumerate(["c0_balance", "c0_income", "c0_value"]):
            fig.add_trace(go.Scatter(
                x=df["game_date"], y=df[col],
                name=label, mode="lines",
                line=dict(color=color, width=2),
                showlegend=(i == 0),
                hovertemplate="%{customdata}: %{y:,.0f}<extra>" + label + "</extra>",
                customdata=df["game_date"].apply(game_date_to_str),
            ), row=i + 1, col=1)

    if not all_dates.empty:
        _apply_date_xaxis(fig, all_dates, row=3, col=1)
    fig.update_layout(
        title="Company 0 Finances Over Time",
        template=_TEMPLATE, height=700,
        legend=dict(orientation="h", y=1.04),
    )
    return fig


def company_loan_balance(sessions: list[SessionData]) -> go.Figure:
    """Balance vs loan over time for each session."""
    fig = go.Figure()
    all_dates = _all_game_dates(sessions)

    for s in sessions:
        if s.snapshots.empty:
            continue
        df = s.snapshots.sort_values("game_date")
        color = MODEL_COLORS.get(s.model, "#999")
        date_labels = df["game_date"].apply(game_date_to_str)

        fig.add_trace(go.Scatter(
            x=df["game_date"], y=df["c0_balance"],
            name=f"{s.model} balance", mode="lines",
            line=dict(color=color, width=2),
            hovertemplate="%{customdata}: %{y:,.0f}<extra>balance</extra>",
            customdata=date_labels,
        ))
        fig.add_trace(go.Scatter(
            x=df["game_date"], y=df["c0_loan"],
            name=f"{s.model} loan", mode="lines",
            line=dict(color=color, width=1, dash="dot"),
            hovertemplate="%{customdata}: %{y:,.0f}<extra>loan</extra>",
            customdata=date_labels,
        ))

    if not all_dates.empty:
        _apply_date_xaxis(fig, all_dates)
    fig.update_layout(
        title="Balance vs Loan Over Time",
        yaxis_title="Amount",
        template=_TEMPLATE, height=400,
    )
    return fig


# ---------------------------------------------------------------------------
# Game progression
# ---------------------------------------------------------------------------

def entity_growth_timeseries(sessions: list[SessionData]) -> go.Figure:
    """Vehicles, stations over game time."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        subplot_titles=("Vehicles", "Stations"),
        vertical_spacing=0.12,
    )

    all_dates = _all_game_dates(sessions)
    for s in sessions:
        if s.snapshots.empty:
            continue
        df = s.snapshots.sort_values("game_date")
        color = MODEL_COLORS.get(s.model, "#999")
        label = _short_label(s)
        date_labels = df["game_date"].apply(game_date_to_str)

        for i, col in enumerate(["num_vehicles", "num_stations"]):
            fig.add_trace(go.Scatter(
                x=df["game_date"], y=df[col],
                name=label, mode="lines",
                line=dict(color=color, width=2),
                showlegend=(i == 0),
                hovertemplate="%{customdata}: %{y}<extra>" + label + "</extra>",
                customdata=date_labels,
            ), row=i + 1, col=1)

    if not all_dates.empty:
        _apply_date_xaxis(fig, all_dates, row=2, col=1)
    fig.update_layout(
        title="Infrastructure Growth Over Time",
        template=_TEMPLATE, height=500,
        legend=dict(orientation="h", y=1.05),
    )
    return fig


# ---------------------------------------------------------------------------
# Action analysis
# ---------------------------------------------------------------------------

def action_type_distribution(sessions: list[SessionData]) -> go.Figure:
    """Horizontal bar: action types split by success/fail, per session."""
    fig = make_subplots(
        rows=1, cols=len(sessions),
        subplot_titles=[_short_label(s) for s in sessions],
        shared_yaxes=True,
        horizontal_spacing=0.15,
    )

    for i, s in enumerate(sessions):
        if s.actions.empty:
            continue
        counts = s.actions.groupby(["action_type", "status"]).size().reset_index(name="count")
        for status, color in [("success", "#2CA02C"), ("failed", "#D62728")]:
            subset = counts[counts["status"] == status]
            fig.add_trace(go.Bar(
                y=subset["action_type"], x=subset["count"],
                name=status, orientation="h",
                marker_color=color,
                showlegend=(i == 0),
            ), row=1, col=i + 1)

    n_types = max((s.actions["action_type"].nunique() for s in sessions if not s.actions.empty), default=10)
    fig.update_layout(
        title="Action Types: Success vs Failure",
        barmode="stack", template=_TEMPLATE,
        height=max(450, 28 * n_types),
        legend=dict(orientation="h", y=1.05),
        margin=dict(l=160),
    )
    return fig


def action_success_by_type(sessions: list[SessionData]) -> go.Figure:
    """Heatmap: success rate per action_type per model (top 15 types)."""
    combined = pd.concat(
        [s.actions.assign(_model=s.model) for s in sessions if not s.actions.empty],
        ignore_index=True,
    )
    total = combined.groupby(["_model", "action_type"]).size().reset_index(name="total")
    ok = combined[combined["status"] == "success"].groupby(
        ["_model", "action_type"],
    ).size().reset_index(name="ok")
    merged = total.merge(ok, on=["_model", "action_type"], how="left").fillna(0)
    merged["rate"] = merged["ok"] / merged["total"] * 100

    top_types = merged.groupby("action_type")["total"].sum().nlargest(15).index
    merged = merged[merged["action_type"].isin(top_types)]

    pivot = merged.pivot(index="action_type", columns="_model", values="rate").fillna(0)
    fig = px.imshow(
        pivot, text_auto=".0f", color_continuous_scale="RdYlGn",
        zmin=0, zmax=100,
        labels=dict(x="Model", y="Action Type", color="Success %"),
        title="Success Rate by Action Type (top 15)",
    )
    fig.update_layout(template=_TEMPLATE, height=500, margin=dict(l=180))
    return fig


def actions_per_agent_bar(sessions: list[SessionData]) -> go.Figure:
    """Grouped bar: successful vs failed actions per agent per model."""
    rows = []
    for s in sessions:
        if s.actions.empty:
            continue
        for agent_id in s.actions["agent_id"].unique():
            adf = s.actions[s.actions["agent_id"] == agent_id]
            rows.append({
                "agent": agent_id,
                "model": s.model,
                "successful": int((adf["status"] == "success").sum()),
                "failed": int((adf["status"] != "success").sum()),
            })

    df = pd.DataFrame(rows)
    fig = go.Figure()
    for model in df["model"].unique():
        mdf = df[df["model"] == model]
        fig.add_trace(go.Bar(
            x=mdf["agent"], y=mdf["successful"],
            name=f"{model} ok", marker_color=MODEL_COLORS.get(model, "#999"),
        ))
        fig.add_trace(go.Bar(
            x=mdf["agent"], y=mdf["failed"],
            name=f"{model} fail",
            marker_color=MODEL_COLORS.get(model, "#999"),
            marker_pattern_shape="/", opacity=0.5,
        ))

    fig.update_layout(
        title="Actions per Agent: Successful vs Failed",
        barmode="group", template=_TEMPLATE, height=400,
    )
    return fig


# ---------------------------------------------------------------------------
# Cycle timing
# ---------------------------------------------------------------------------

def cycle_timing_boxplots(sessions: list[SessionData]) -> go.Figure:
    """Box plots of decide and execute timing per agent and model."""
    combined = pd.concat(
        [s.agent_cycles.assign(_model=s.model) for s in sessions if not s.agent_cycles.empty],
        ignore_index=True,
    )
    combined["agent"] = combined["connection_id"].str.split(":").str[2]

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=("Decide (ms)", "Execute (ms)"),
        horizontal_spacing=0.12,
    )

    for i, metric in enumerate(["decide_ms", "execute_ms"]):
        for model in combined["_model"].unique():
            mdf = combined[combined["_model"] == model]
            fig.add_trace(go.Box(
                y=mdf[metric], x=mdf["agent"],
                name=model,
                marker_color=MODEL_COLORS.get(model, "#999"),
                showlegend=(i == 0),
            ), row=1, col=i + 1)

    fig.update_layout(
        title="Cycle Timing Distribution by Agent",
        boxmode="group", template=_TEMPLATE, height=450,
        legend=dict(orientation="h", y=1.08),
    )
    return fig


def cycle_decide_over_time(sessions: list[SessionData]) -> go.Figure:
    """Line chart: decide_ms per cycle number, per agent, per model."""
    fig = go.Figure()
    for s in sessions:
        if s.agent_cycles.empty:
            continue
        df = s.agent_cycles.copy()
        df["agent"] = df["connection_id"].str.split(":").str[2]
        for agent in sorted(df["agent"].unique()):
            adf = df[df["agent"] == agent].sort_values("cycle_number")
            color = AGENT_COLORS.get(agent, "#999")
            dash = "solid" if s.model == "gpt-5.2" else "dot"
            fig.add_trace(go.Scatter(
                x=adf["cycle_number"], y=adf["decide_ms"],
                name=f"{s.model} / {agent}", mode="lines",
                line=dict(width=1.5, color=color, dash=dash),
                opacity=0.8,
            ))

    fig.update_layout(
        title="LLM Decide Latency Over Cycles",
        xaxis_title="Cycle Number", yaxis_title="Decide (ms)",
        template=_TEMPLATE, height=450,
        legend=dict(font=dict(size=10)),
    )
    return fig


def actions_per_cycle_scatter(sessions: list[SessionData]) -> go.Figure:
    """Scatter: actions proposed vs succeeded per cycle."""
    combined = pd.concat(
        [s.agent_cycles.assign(_model=s.model)
         for s in sessions if not s.agent_cycles.empty],
        ignore_index=True,
    )
    combined["agent"] = combined["connection_id"].str.split(":").str[2]

    fig = px.scatter(
        combined, x="actions_proposed", y="actions_succeeded",
        color="_model", symbol="agent",
        color_discrete_map=MODEL_COLORS,
        title="Actions Proposed vs Succeeded per Cycle",
        labels={"actions_proposed": "Proposed", "actions_succeeded": "Succeeded",
                "_model": "Model", "agent": "Agent"},
        opacity=0.6,
    )
    max_val = max(combined["actions_proposed"].max(), combined["actions_succeeded"].max(), 1)
    fig.add_shape(type="line", x0=0, y0=0, x1=max_val, y1=max_val,
                  line=dict(dash="dash", color="gray", width=1))
    fig.update_layout(template=_TEMPLATE, height=450)
    return fig


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def events_timeline(sessions: list[SessionData]) -> go.Figure:
    """Timeline of game events with readable dates."""
    combined = pd.concat(
        [s.events.assign(_model=s.model) for s in sessions if not s.events.empty],
        ignore_index=True,
    )
    if combined.empty:
        return go.Figure().update_layout(title="No events data")

    combined["date_label"] = combined["game_date"].apply(game_date_to_str)

    fig = px.scatter(
        combined, x="game_date", y="_model",
        color="event_type", hover_data=["date_label", "detail", "company_id"],
        title="Game Events Timeline",
        labels={"_model": "Model"},
    )
    fig.update_traces(marker=dict(size=12, symbol="diamond"))

    all_dates = combined["game_date"]
    vals, labels = _date_tickvals(all_dates, n_ticks=6)
    fig.update_xaxes(tickvals=vals, ticktext=labels, title="")
    fig.update_layout(template=_TEMPLATE, height=300)
    return fig


# ---------------------------------------------------------------------------
# Batch rendering
# ---------------------------------------------------------------------------

def generate_all_plots(
    sessions: list[SessionData],
    output_dir: str | None = None,
) -> list[go.Figure]:
    """Generate all analysis plots. Saves to output_dir if provided."""
    from pathlib import Path

    figs: list[tuple[str, go.Figure]] = [
        ("01_overview", session_overview_table(sessions)),
        ("02_agent_performance", agent_performance_bars(sessions)),
        ("03_success_heatmap", agent_success_rate_heatmap(sessions)),
        ("04_finances", company_finances_timeseries(sessions)),
        ("05_balance_vs_loan", company_loan_balance(sessions)),
        ("06_entity_growth", entity_growth_timeseries(sessions)),
        ("07_action_types", action_type_distribution(sessions)),
        ("08_action_success_by_type", action_success_by_type(sessions)),
        ("09_actions_per_agent", actions_per_agent_bar(sessions)),
        ("10_cycle_timing", cycle_timing_boxplots(sessions)),
        ("11_decide_latency", cycle_decide_over_time(sessions)),
        ("12_actions_scatter", actions_per_cycle_scatter(sessions)),
        ("13_events", events_timeline(sessions)),
    ]

    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name, fig in figs:
            fig.write_html(str(out / f"{name}.html"))
            try:
                fig.write_image(str(out / f"{name}.png"), scale=2, width=1200, height=fig.layout.height or 500)
            except Exception:
                pass

    return [fig for _, fig in figs]
