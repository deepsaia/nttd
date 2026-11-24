"""Evaluate recorded companies and compare experiment means over game days."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from nttd.analysis.pareto import AXES, cumulative_revenue, pareto_fronts

TITLES = {
    "company_value": "Company value", "episode_revenue": "Revenue over the run",
    "total_cargo": "Cargo delivered", "performance_rating": "Performance rating",
}
COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6", "#e34948")


@dataclass
class RunEvaluation:
    path: Path
    series: pd.DataFrame
    cost_usd: float | None
    tokens: int | None
    cost_source: str
    revenue_source: str = "unavailable"


def session_directory(path: Path) -> Path:
    """Accept a session directory or a parent containing exactly one session."""
    path = Path(path).resolve()
    if (path / "snapshots.parquet").is_file():
        return path
    matches = list(path.rglob("snapshots.parquet")) if path.is_dir() else []
    if len(matches) != 1:
        raise ValueError(f"{path}: expected one snapshots.parquet, found {len(matches)}; pass a session directory")
    return matches[0].parent


def read_run(path: Path, company_id: int = 0) -> RunEvaluation:
    """Read game metrics and optional reported spend, without a runner dependency."""
    root = Path(path).resolve()
    session = session_directory(root)
    result_path = session / "result.parquet"
    result = {}
    if result_path.exists():
        result = next((r for r in pd.read_parquet(result_path).to_dict("records")
                       if r["company_id"] == company_id), {})
    snapshots = pd.read_parquet(session / "snapshots.parquet").sort_values("game_date", kind="stable")
    points, finances = [], []
    for row in snapshots.to_dict("records"):
        company = next((c for c in json.loads(row["snapshot_json"]).get("companies", [])
                        if c["id"] == company_id), None)
        if company is None:
            continue
        points.append({
            "game_date": int(row["game_date"]),
            "company_value": float(company["value"]),
            "quarter_income": float(company["q0_income"]),
            "total_cargo": float(company["cargo_delivered_total"]),
            "performance_rating": float(company["performance_rating"]),
        })
        finances.append(company)
    if not points:
        raise ValueError(f"{session}: no snapshots for company {company_id}")
    frame = pd.DataFrame(points)
    explicit_periods = all(c.get("finance_quarter") is not None for c in finances)
    historical_quarters = [c.get("completed_quarter_income", []) for c in finances]
    last_completed = [c["q1_income"] if c.get("q1_income") is not None else c.get("income")
                      for c in finances]
    revenue_source = ("economy_quarter_history" if explicit_periods else
                      "legacy_completed_quarters_inferred_periods" if any(v is not None for v in last_completed)
                      else "current_quarter_only")
    frame["episode_revenue"] = cumulative_revenue(
        frame["game_date"].tolist(), frame["quarter_income"].tolist(),
        finance_quarters=[c["finance_quarter"] for c in finances] if explicit_periods else None,
        completed_quarter_income=historical_quarters,
        last_completed_quarter_income=last_completed,
        initial_income=float(frame["quarter_income"].iloc[0]),
    )
    start = result.get("start_game_date")
    if start is None or pd.isna(start):
        start = frame["game_date"].iloc[0]
    frame["day"] = frame["game_date"] - int(start)
    frame = frame[frame["day"] >= 0].groupby("day", sort=True).tail(1).set_index("day")[list(AXES)]
    if frame.empty:
        raise ValueError(f"{session}: no snapshots at or after the recorded start date")
    # Carry observations over unsampled days, but preserve explicitly unknown values.
    frame = frame.reindex(range(int(frame.index.min()), int(frame.index.max()) + 1), method="ffill")
    frame.index.name = "day"
    cost = float(result["total_cost_usd"]) if result.get("cost_is_reported") else None
    tokens = int(result["prompt_tokens"] + result["completion_tokens"]) if result.get("spend_is_reported") else None
    source = "result.parquet" if cost is not None else "unavailable"
    # Optional caller-supplied usage log. Its cost covers the whole runner lifetime.
    usage = root / "costs.csv"
    if usage.is_file():
        costs = pd.read_csv(usage)
        if not costs.empty:
            if "total_cost_usd" in costs:
                cost = float(costs["total_cost_usd"].iloc[-1])
            else:
                cost = float(costs["cost_usd"].sum())
            tokens = int(costs["input_tokens"].sum() + costs["output_tokens"].sum())
            source = str(usage)
    return RunEvaluation(session, frame, cost, tokens, source, revenue_source)


def complete_mean(values: list[float | int | None]) -> float | None:
    """Do not turn absent spend into zero or average only the reporting seeds."""
    return sum(values) / len(values) if all(v is not None for v in values) else None


def markdown_table(table: pd.DataFrame) -> str:
    """A table with explicit missing values and cents preserved for cost."""
    lines = ["| experiment | " + " | ".join(table.columns) + " |",
             "|---|" + "---|" * len(table.columns)]
    for label, row in table.iterrows():
        cells = []
        for key, value in row.items():
            cells.append("n/a" if pd.isna(value) else format(value, ",.2f" if key == "cost_usd" else ",.0f"))
        lines.append("| " + str(label).replace("|", "\\|") + " | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def evaluate(
    experiments: Mapping[str, Sequence[Path]], output: Path,
    *, company_id: int = 0, png: bool = False,
) -> pd.DataFrame:
    """Save evaluation tables and curves. Repeated runs within a group are rejected.

    Curves and rankings use the last day reached by every run in a group. Groups
    with different horizons retain their own horizons, displayed in the table.
    Per-run final values and cost provenance are also saved in runs.csv.
    """
    if not experiments or any(not paths for paths in experiments.values()):
        raise ValueError("Supply at least one run per experiment")
    data, summaries, run_rows, curves = {}, {}, [], []
    for label, paths in experiments.items():
        runs = [read_run(Path(path), company_id) for path in paths]
        if len({run.path for run in runs}) != len(runs):
            raise ValueError(f"{label}: duplicate session")
        first = max(int(run.series.index.min()) for run in runs)
        last = min(int(run.series.index.max()) for run in runs)
        if first > last:
            raise ValueError(f"{label}: runs have no overlapping game days")
        grouped = pd.concat([run.series.loc[first:last] for run in runs]).groupby(level=0)
        mean = grouped.mean().where(grouped.count() == len(runs))
        data[label] = (mean, runs)
        summaries[label] = {
            "seeds": len(runs), "day": last, **mean.iloc[-1].to_dict(),
            "cost_usd": complete_mean([run.cost_usd for run in runs]),
            "tokens": complete_mean([run.tokens for run in runs]),
        }
        curves.append(mean.reset_index().assign(experiment=label))
        for run in runs:
            run_rows.append({"experiment": label, "session": str(run.path),
                             "day": int(run.series.index.max()), **run.series.iloc[-1].to_dict(),
                             "cost_usd": run.cost_usd, "tokens": run.tokens, "cost_source": run.cost_source,
                             "revenue_source": run.revenue_source})
    table = pd.DataFrame.from_dict(summaries, orient="index")
    fronts = pareto_fronts({label: tuple(row[list(AXES)]) for label, row in table.iterrows()
                           if row[list(AXES)].notna().all()})
    table.insert(0, "front", pd.Series(fronts, dtype=float))
    table = table.sort_values(["front", "cost_usd"])
    table.index.name = "experiment"
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    table.to_csv(output / "evaluation.csv")
    table.reset_index().to_json(output / "evaluation.json", orient="records", indent=2)
    pd.DataFrame(run_rows).to_csv(output / "runs.csv", index=False)
    pd.concat(curves).to_csv(output / "curves.csv", index=False)
    note = ("Curves and ranks use each group's common game-day horizon (the day column). "
            "Day zero is the recorded result start, or the first snapshot if unavailable. "
            "Revenue starts at the first financial observation and excludes its opening current-quarter revenue. "
            "Cost is reported total run spend, including any calls after the game ended; "
            "missing spend or completed-quarter history is unavailable, not zero. "
            "Means require every seed; conditions with missing metrics receive no Pareto rank. "
            "Legacy quarter periods are inferred; see runs.csv for revenue and cost sources.\n\n")
    (output / "evaluation.md").write_text(note + markdown_table(table))
    fig = make_subplots(rows=2, cols=3, subplot_titles=[*TITLES.values(), "Reported LLM cost (USD)", "Pareto front"])
    by_front = table.groupby("front")
    front_offsets = by_front.cumcount() - (by_front["front"].transform("size") - 1) / 2
    for index, (label, (mean, runs)) in enumerate(data.items()):
        color = COLORS[index % len(COLORS)]
        for panel, key in enumerate(AXES):
            fig.add_trace(go.Scatter(x=mean.index, y=mean[key], name=f"{label} (n={len(runs)})",
                                    legendgroup=label, showlegend=panel == 0, line={"color": color}),
                          row=panel // 3 + 1, col=panel % 3 + 1)
            fig.update_xaxes(title_text="Game days since start", row=panel // 3 + 1, col=panel % 3 + 1)
        costs = [run.cost_usd for run in runs if run.cost_usd is not None]
        if costs:
            fig.add_trace(go.Box(y=costs, name=label, boxpoints="all", marker_color=color,
                                legendgroup=label, showlegend=False), row=2, col=2)
        if label not in fronts:
            continue
        fig.add_trace(go.Scatter(x=[front_offsets[label]], y=[int(fronts[label])], mode="markers",
                                 name=label, text=[label], marker={"color": color, "size": 11},
                                 legendgroup=label, showlegend=False,
                                 hovertemplate="%{text}<br>Front %{y}<extra></extra>"),
                      row=2, col=3)
    fig.update_layout(title="NTTD evaluation: mean over runs in each group", template="plotly_white",
                      height=850, width=1600, legend={"orientation": "h", "y": -0.18})
    fig.update_xaxes(visible=False, row=2, col=3)
    fig.update_yaxes(tick0=1, dtick=1, range=[max(fronts.values(), default=1) + 0.5, 0.5],
                     title_text="Front (1 = not dominated)", row=2, col=3)
    fig.write_html(output / "metrics.html", include_plotlyjs=True)
    if png:
        try:
            fig.write_image(output / "metrics.png", scale=2)
        except RuntimeError as exc:
            raise RuntimeError(
                f"Tables and HTML were saved to {output}. PNG export failed; "
                "check the Kaleido/Chrome installation or omit --png. " + str(exc)
            ) from exc
    return table
