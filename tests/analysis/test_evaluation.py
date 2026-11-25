"""Evaluation works from standalone session artifacts, with no runner package."""

import json

import pandas as pd
import pytest
from typer.testing import CliRunner

from nttd.analysis.evaluation import evaluate, read_run
from nttd.cli.app import app


def record(root, name, values, *, start=730485, company=0):
    path = root / name
    path.mkdir()
    pd.DataFrame([
        {"game_date": start + day, "snapshot_json": json.dumps({"companies": [{
            "id": company, "value": value, "q0_income": day * 10,
            "cargo_delivered_total": day * 2, "performance_rating": 20 + day,
        }]})} for day, value in enumerate(values)
    ]).to_parquet(path / "snapshots.parquet")
    pd.DataFrame([{"company_id": company, "start_game_date": start,
                   "total_cost_usd": 0, "cost_is_reported": False,
                   "spend_is_reported": False}]).to_parquet(path / "result.parquet")
    return path


def test_group_alignment_missing_spend_and_outputs(tmp_path):
    a = record(tmp_path, "a", [10, 20, 30])
    b = record(tmp_path, "b", [20, 40, 60, 80])
    out = tmp_path / "out"
    table = evaluate({"experiment": [a, b]}, out)
    assert table.loc["experiment", "company_value"] == 45
    assert table.loc["experiment", "day"] == 2
    assert table.loc["experiment", "seeds"] == 2
    assert pd.isna(table.loc["experiment", "cost_usd"])
    runs = pd.read_csv(out / "runs.csv")
    assert runs["company_value"].tolist() == [30, 80]
    assert json.loads((out / "evaluation.json").read_text())[0]["cost_usd"] is None
    assert (out / "metrics.html").stat().st_size > 1000
    assert set(pd.read_csv(out / "curves.csv")["day"]) == {0, 1, 2}


def test_company_selection_start_date_and_cost_sources(tmp_path):
    path = record(tmp_path, "session", [10, 20, 30], company=2)
    pd.DataFrame([{"company_id": 2, "start_game_date": 730486,
                   "total_cost_usd": 1.25, "cost_is_reported": True,
                   "spend_is_reported": True, "prompt_tokens": 10,
                   "completion_tokens": 2}]).to_parquet(path / "result.parquet")
    run = read_run(path, 2)
    assert run.series.index.tolist() == [0, 1]
    assert run.series.iloc[0]["company_value"] == 20
    assert (run.cost_usd, run.tokens) == (1.25, 12)
    pd.DataFrame([{"total_cost_usd": 3.45, "input_tokens": 20,
                   "output_tokens": 5}]).to_csv(path / "costs.csv", index=False)
    run = read_run(path, 2)
    assert (run.cost_usd, run.tokens) == (3.45, 25)
    assert "3.45" in (evaluate({"a": [path]}, tmp_path / "out", company_id=2).to_string())


def test_cli_paths_groups_and_ambiguous_parent(tmp_path):
    a = record(tmp_path, "a", [1, 2])
    b = record(tmp_path, "b", [2, 4])
    result = CliRunner().invoke(app, ["evaluate", f"Luna={a}", f"Luna={b}", "-o", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    rows = json.loads((tmp_path / "out/evaluation.json").read_text())
    assert rows[0]["experiment"] == "Luna" and rows[0]["seeds"] == 2
    with pytest.raises(ValueError, match="expected one"):
        read_run(tmp_path)
    with pytest.raises(ValueError, match="duplicate"):
        evaluate({"a": [a, a]}, tmp_path / "duplicates")


def test_ranks_and_partial_costs(tmp_path):
    a = record(tmp_path, "a", [10, 20])
    b = record(tmp_path, "b", [20, 40])
    pd.DataFrame([{"total_cost_usd": 2, "input_tokens": 10,
                   "output_tokens": 1}]).to_csv(a / "costs.csv", index=False)
    table = evaluate({"weak": [a], "strong": [b], "mean": [a, b]}, tmp_path / "out")
    assert table.loc["strong", "front"] == 1
    assert table.loc["weak", "front"] == 3
    assert pd.isna(table.loc["mean", "cost_usd"])


def test_pareto_plot_spreads_conditions_on_each_front(tmp_path, monkeypatch):
    a = record(tmp_path, "a", [10, 20])
    b = record(tmp_path, "b", [20, 40])
    c = record(tmp_path, "c", [20, 40])
    figures = []
    monkeypatch.setattr("plotly.graph_objects.Figure.write_html",
                        lambda figure, *args, **kwargs: figures.append(figure))

    evaluate({"weak": [a], "strong": [b], "tied": [c]}, tmp_path / "out")

    figure, = figures
    dots = {trace.name: trace for trace in figure.data if trace.yaxis == "y6"}
    assert set(dots) == {"weak", "strong", "tied"}
    assert all(dot.mode == "markers" for dot in dots.values())
    assert tuple(dots["strong"].y) == tuple(dots["tied"].y) == (1,)
    assert dots["strong"].x[0] != dots["tied"].x[0]
    assert tuple(dots["weak"].y) == (2,)
    assert tuple(figure.layout.yaxis6.range) == (2.5, 0.5)


def test_sparse_unsorted_snapshots_and_parent_directory(tmp_path):
    parent = tmp_path / "run"
    parent.mkdir()
    path = record(parent, "session", [10, 20, 30, 40])
    snapshots = pd.read_parquet(path / "snapshots.parquet")
    snapshots.iloc[[3, 0, 2]].to_parquet(path / "snapshots.parquet")
    run = read_run(parent)
    assert run.series["company_value"].tolist() == [10, 10, 30, 40]
    # A directory without a result still yields a curve from its first snapshot.
    (path / "result.parquet").unlink()
    assert read_run(parent).series.index.tolist() == [0, 1, 2, 3]


def test_png_failure_keeps_html_and_returns_cli_error(tmp_path, monkeypatch):
    path = record(tmp_path, "run", [10, 20])
    def fail(*args, **kwargs):
        raise RuntimeError("Chrome unavailable")
    monkeypatch.setattr("plotly.graph_objects.Figure.write_image", fail)
    out = tmp_path / "out"
    result = CliRunner().invoke(app, ["evaluate", str(path), "--png", "-o", str(out)])
    assert result.exit_code == 1
    assert "PNG export failed" in result.output
    assert (out / "metrics.html").exists()
    assert (out / "evaluation.json").exists()


def test_completed_history_corrects_quarter_undersampling_and_opening_balance(tmp_path):
    path = record(tmp_path, "run", [10, 20, 30])
    snapshots = pd.read_parquet(path / "snapshots.parquet")
    for row, (quarter, current, history) in enumerate([(10, 100, []), (10, 150, []), (11, 20, [300])]):
        snapshot = json.loads(snapshots.loc[row, "snapshot_json"])
        snapshot["companies"][0].update(finance_quarter=quarter, q0_income=current,
                                        completed_quarter_income=history)
        snapshots.loc[row, "snapshot_json"] = json.dumps(snapshot)
    snapshots.to_parquet(path / "snapshots.parquet")
    run = read_run(path)
    assert run.revenue_source == "economy_quarter_history"
    assert run.series["episode_revenue"].tolist() == [0, 50, 220]


def test_unknown_history_stays_unknown_in_curves_means_and_rank(tmp_path):
    complete = record(tmp_path, "complete", [10, 20, 30, 40])
    missing = record(tmp_path, "missing", [10, 20, 30, 40])
    for path in [complete, missing]:
        snapshots = pd.read_parquet(path / "snapshots.parquet")
        for row in range(4):
            snapshot = json.loads(snapshots.loc[row, "snapshot_json"])
            snapshot["companies"][0].update(
                finance_quarter=10 if row < 2 else 11,
                completed_quarter_income=[200] if path == complete and row >= 2 else [],
            )
            snapshots.loc[row, "snapshot_json"] = json.dumps(snapshot)
        snapshots.iloc[[0, 1, 3]].to_parquet(path / "snapshots.parquet")
    run = read_run(missing)
    assert run.series["episode_revenue"].iloc[:3].tolist() == [0, 10, 10]
    assert pd.isna(run.series["episode_revenue"].iloc[3])
    table = evaluate({"known": [complete], "partial": [complete, missing]}, tmp_path / "out")
    assert table.loc["partial", "seeds"] == 2
    assert pd.isna(table.loc["partial", "episode_revenue"])
    assert pd.isna(table.loc["partial", "front"])
    assert table.loc["known", "episode_revenue"] == 230
    assert table.loc["known", "front"] == 1
    assert table.loc["partial", "company_value"] == 40


def test_legacy_snapshot_without_completed_history_is_not_exact_after_rollover(tmp_path):
    path = record(tmp_path, "run", [10, 20], start=715965)
    run = read_run(path)
    assert run.revenue_source == "current_quarter_only"
    assert pd.isna(run.series["episode_revenue"].iloc[-1])
