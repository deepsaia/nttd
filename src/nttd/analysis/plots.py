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

# Consistent color palette -- maps agent type keywords to colors.
# Lookup normalizes agent_id (strip separators, lowercase) to match.
_AGENT_TYPE_COLORS: dict[str, str] = {
    "road": "#4C78A8",
    "rail": "#F58518",
    "air": "#E45756",
    "water": "#72B7B2",
    "general": "#B07AA1",
}

# Fallback palette for unknown agent IDs
_EXTRA_COLORS = ["#FF9DA7", "#9C755F", "#BAB0AC", "#FABFD2", "#D4A6C8"]


def get_agent_color(agent_id: str) -> str:
    """Get a consistent color for an agent_id, matching by transport type keyword."""
    normalized = agent_id.lower().replace("-", "_")
    for type_key, color in _AGENT_TYPE_COLORS.items():
        if type_key in normalized:
            return color
    # Deterministic fallback for unknown agent IDs
    idx = hash(agent_id) % len(_EXTRA_COLORS)
    return _EXTRA_COLORS[idx]


# Legacy alias for any code that imports AGENT_COLORS directly
AGENT_COLORS = _AGENT_TYPE_COLORS

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
        height=700, legend=dict(orientation="h", y=1.08, font=dict(size=10)),
        margin=dict(t=80),
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
        template=_TEMPLATE, height=750,
        legend=dict(orientation="h", y=1.06, font=dict(size=10)),
        margin=dict(t=80),
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
        template=_TEMPLATE, height=550,
        legend=dict(orientation="h", y=1.08, font=dict(size=10)),
        margin=dict(t=80),
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
        height=max(500, 28 * n_types),
        legend=dict(orientation="h", y=1.08, font=dict(size=10)),
        margin=dict(l=160, t=80),
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
        boxmode="group", template=_TEMPLATE, height=500,
        legend=dict(orientation="h", y=1.1, font=dict(size=10)),
        margin=dict(t=80),
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
            color = get_agent_color(agent)
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
# Per-transport finances
# ---------------------------------------------------------------------------

# Action types that cost money (infrastructure builds, vehicle purchases)
_COSTLY_ACTIONS = {
    "connect_road", "build_road_depot", "build_road_stop",
    "connect_rail", "build_rail_station", "build_rail_depot",
    "build_rail_signal", "build_rail_waypoint",
    "build_path", "build_canal", "build_lock", "build_buoy", "build_water_depot",
    "build_airport", "build_dock", "build_bridge", "build_tunnel",
    "buy_vehicle",
}


def agent_spending_proxy(sessions: list[SessionData]) -> go.Figure:
    """Per-agent cumulative costly actions over time, overlaid with company balance.

    For existing sessions that lack per-transport finance data, this shows
    which agent's build activity correlates with balance changes.
    """
    fig = make_subplots(
        rows=1, cols=len(sessions),
        subplot_titles=[_short_label(s) for s in sessions],
        specs=[[{"secondary_y": True}] * len(sessions)],
        horizontal_spacing=0.12,
    )

    all_dates = _all_game_dates(sessions)
    for i, s in enumerate(sessions):
        if s.actions.empty:
            continue
        col = i + 1
        costly = s.actions[
            (s.actions["status"] == "success") & (s.actions["action_type"].isin(_COSTLY_ACTIONS))
        ].copy()

        for agent_id in sorted(costly["agent_id"].unique()):
            adf = costly[costly["agent_id"] == agent_id].sort_values("game_date")
            adf = adf.copy()
            adf["cumulative"] = range(1, len(adf) + 1)
            color = get_agent_color(agent_id)
            fig.add_trace(go.Scatter(
                x=adf["game_date"], y=adf["cumulative"],
                name=agent_id if i == 0 else None,
                mode="lines", line=dict(color=color, width=2),
                showlegend=(i == 0),
                hovertemplate="%{customdata}: %{y} builds<extra>" + agent_id + "</extra>",
                customdata=adf["game_date"].apply(game_date_to_str),
            ), row=1, col=col, secondary_y=False)

        if not s.snapshots.empty:
            df = s.snapshots.sort_values("game_date")
            fig.add_trace(go.Scatter(
                x=df["game_date"], y=df["c0_balance"],
                name="Balance" if i == 0 else None,
                mode="lines", line=dict(color="#333", width=1, dash="dot"),
                showlegend=(i == 0),
                hovertemplate="%{customdata}: %{y:,.0f}<extra>balance</extra>",
                customdata=df["game_date"].apply(game_date_to_str),
            ), row=1, col=col, secondary_y=True)

    if not all_dates.empty:
        for i in range(len(sessions)):
            _apply_date_xaxis(fig, all_dates, row=1, col=i + 1)
    fig.update_yaxes(title_text="Cumulative Builds", secondary_y=False)
    fig.update_yaxes(title_text="Balance", secondary_y=True)
    fig.update_layout(
        title="Agent Infrastructure Spending vs Company Balance",
        template=_TEMPLATE, height=500,
        legend=dict(orientation="h", y=1.12, font=dict(size=10)),
        margin=dict(t=80),
    )
    return fig


def transport_mode_finances(sessions: list[SessionData]) -> go.Figure:
    """Per-transport-mode revenue (vehicle profits) and infrastructure costs.

    Extracts vehicle profits grouped by type (train/road/ship/aircraft) and
    infrastructure maintenance costs from snapshot_json. Requires sessions
    captured with vehicle tracking enabled (post-fix).
    """
    import json

    fig = make_subplots(
        rows=2, cols=len(sessions),
        subplot_titles=[f"{_short_label(s)} - Revenue" for s in sessions]
                       + [f"{_short_label(s)} - Infra Costs" for s in sessions],
        shared_xaxes=True, vertical_spacing=0.15, horizontal_spacing=0.12,
    )

    type_colors = {
        "train": "#F58518", "road": "#4C78A8",
        "aircraft": "#E45756", "ship": "#72B7B2",
    }

    all_dates = _all_game_dates(sessions)
    has_data = False

    for i, s in enumerate(sessions):
        if s.snapshots.empty:
            continue
        col = i + 1
        df = s.snapshots.sort_values("game_date")

        # Extract per-vehicle-type profit from snapshot_json
        type_profits: dict[str, list[tuple[int, int]]] = {}
        infra_series: dict[str, list[tuple[int, int]]] = {}

        for _, row in df.iterrows():
            gd = row["game_date"]
            try:
                data = json.loads(row["snapshot_json"])
            except (json.JSONDecodeError, TypeError):
                continue

            # Vehicle profits by type
            for v in data.get("vehicles", []):
                vtype = v.get("type", "unknown")
                if vtype not in type_profits:
                    type_profits[vtype] = []
                type_profits[vtype].append((gd, v.get("profit_this_year", 0)))

            # Infrastructure costs
            for inf in data.get("infrastructure", []):
                if inf.get("company_id", -1) != 0:
                    continue
                for cost_key, label in [
                    ("rail_cost", "rail"), ("road_cost", "road"),
                    ("water_cost", "water"), ("airport_cost", "air"),
                ]:
                    val = inf.get(cost_key, 0)
                    if val != 0:
                        has_data = True
                    if label not in infra_series:
                        infra_series[label] = []
                    infra_series[label].append((gd, val))

        # Plot vehicle revenue by type
        for vtype, points in sorted(type_profits.items()):
            if not points:
                continue
            has_data = True
            pdf = pd.DataFrame(points, columns=["game_date", "profit"])
            agg = pdf.groupby("game_date")["profit"].sum().reset_index()
            agg = agg.sort_values("game_date")
            fig.add_trace(go.Scatter(
                x=agg["game_date"], y=agg["profit"],
                name=vtype if i == 0 else None,
                mode="lines", line=dict(color=type_colors.get(vtype, "#999"), width=2),
                showlegend=(i == 0),
            ), row=1, col=col)

        # Plot infrastructure costs by type
        for label, points in sorted(infra_series.items()):
            if not points:
                continue
            idf = pd.DataFrame(points, columns=["game_date", "cost"])
            idf = idf.drop_duplicates("game_date").sort_values("game_date")
            fig.add_trace(go.Scatter(
                x=idf["game_date"], y=idf["cost"],
                name=f"{label} maint." if i == 0 else None,
                mode="lines", line=dict(color=type_colors.get(
                    {"rail": "train", "road": "road", "air": "aircraft", "water": "ship"}.get(label, label),
                    "#999",
                ), width=2, dash="dash"),
                showlegend=(i == 0),
            ), row=2, col=col)

    if not has_data:
        fig = go.Figure()
        fig.update_layout(
            title="Transport Mode Finances (no vehicle/infrastructure data in these sessions)",
            template=_TEMPLATE, height=200,
        )
        return fig

    if not all_dates.empty:
        for i in range(len(sessions)):
            _apply_date_xaxis(fig, all_dates, row=2, col=i + 1)
    fig.update_layout(
        title="Per-Transport Mode: Vehicle Revenue and Infrastructure Costs",
        template=_TEMPLATE, height=700,
        legend=dict(orientation="h", y=1.08, font=dict(size=10)),
        margin=dict(t=80),
    )
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
        ("14_agent_spending", agent_spending_proxy(sessions)),
        ("15_transport_finances", transport_mode_finances(sessions)),
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
