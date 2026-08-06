"""Metrics that describe how a company was run, not just how it scored.

The performance rating says how well the company did. It cannot distinguish an operator
that borrowed to the limit, ran at a loss for three years and recovered from one that
compounded steadily to the same place, and the difference is the thing a business
benchmark is supposed to be about.

Nothing here is newly recorded. Every value is derived from snapshots.parquet, which
already holds full state per tick, and the action log. That is what lets whoever verifies
a run recompute them and compare, so they are evidence rather than claims.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nttd.analysis import business_metrics


def _snapshot(
    game_date: int,
    *,
    value: int = 0,
    money: int = 0,
    loan: int = 0,
    max_loan: int = 0,
    income: int = 0,
    expenses: int = 0,
    cargo: int = 0,
    vehicles: list[dict[str, Any]] | None = None,
    stations: int = 0,
    maintenance: int = 0,
) -> dict[str, Any]:
    """One snapshot for company 0, in the shape the recorder writes."""
    return {
        "game_date": game_date,
        "snapshot_json": json.dumps({
            "companies": [{
                "id": 0, "value": value, "money": money, "loan": loan,
                "max_loan": max_loan,
                "q0_income": income, "q0_expenses": expenses, "q0_cargo": cargo,
            }],
            "vehicles": vehicles or [],
            "stations": [{"id": i, "company_id": 0} for i in range(stations)],
            "infrastructure": [{"company_id": 0, "rail_cost": maintenance}],
        }),
    }


def _session(tmp_path: Path, snapshots: list[dict[str, Any]]) -> Path:
    session_dir = tmp_path / "ses_test"
    session_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            snapshots,
            schema=pa.schema([("game_date", pa.int32()), ("snapshot_json", pa.large_string())]),
        ),
        session_dir / "snapshots.parquet",
    )
    return session_dir


class TestExpensesAreNegative:
    """The sign that would invert every margin in the file.

    GSCompany.GetQuarterlyExpenses reports expenses as negative money. Confirmed
    across 1,626 recorded samples with no positive case, so profit is income plus
    expenses and the subtraction that reads naturally is wrong.
    """

    def test_profit_adds_the_negative_expense(self, tmp_path: Path) -> None:
        metrics = business_metrics.compute(
            _session(tmp_path, [_snapshot(100, income=1000, expenses=-250, value=1)]), 0,
        )
        assert metrics.operating_margin_final == 0.75

    def test_a_loss_is_reported_as_negative_margin(self, tmp_path: Path) -> None:
        metrics = business_metrics.compute(
            _session(tmp_path, [_snapshot(100, income=1000, expenses=-1500, value=1)]), 0,
        )
        assert metrics.operating_margin_final == -0.5

    def test_quarters_without_revenue_do_not_drag_the_mean(self, tmp_path: Path) -> None:
        """A company that has not started earning has no margin, which is different
        from a margin of zero. Counting them would pull the mean toward zero for every
        run with a slow start."""
        metrics = business_metrics.compute(_session(tmp_path, [
            _snapshot(1, income=0, expenses=-100),
            _snapshot(2, income=0, expenses=-100),
            _snapshot(3, income=1000, expenses=-500),
        ]), 0)
        assert metrics.operating_margin_mean == 0.5


class TestTheRunWideViewSeesWhatTheEndpointCannot:
    def test_peak_borrowing_survives_a_late_repayment(self, tmp_path: Path) -> None:
        """The case the endpoint alone gets wrong: borrowed to the hilt all game,
        repaid in the last quarter, and looks prudent at the finish."""
        metrics = business_metrics.compute(_session(tmp_path, [
            _snapshot(1, loan=270_000, max_loan=300_000, value=100_000),
            _snapshot(2, loan=270_000, max_loan=300_000, value=100_000),
            _snapshot(3, loan=0, max_loan=300_000, value=100_000),
        ]), 0)
        assert metrics.peak_credit_used == 0.9
        assert metrics.final_credit_used == 0.0
        assert metrics.ended_in_debt is False

    def test_borrowing_is_not_measured_against_company_value(self, tmp_path: Path) -> None:
        """Found on real data, not in a fixture. OpenTTD reports company value as 0 or
        1 until the company owns something, so debt-to-value gave a peak leverage of
        250,000 for a company that had simply drawn its starting loan. A guard of
        value > 0 does not catch a value of 1.
        """
        metrics = business_metrics.compute(_session(tmp_path, [
            _snapshot(1, loan=250_000, max_loan=300_000, value=1, money=249_000),
        ]), 0)
        assert 0.0 <= metrics.peak_credit_used <= 1.0
        assert metrics.peak_credit_used == round(250_000 / 300_000, 4)

    def test_lowest_cash_records_how_close_it_ran(self, tmp_path: Path) -> None:
        metrics = business_metrics.compute(_session(tmp_path, [
            _snapshot(1, money=100_000), _snapshot(2, money=12), _snapshot(3, money=80_000),
        ]), 0)
        assert metrics.min_cash == 12

    def test_the_trajectory_is_sampled_across_the_run(self, tmp_path: Path) -> None:
        """Steady compounding and a late scramble reach the same endpoint."""
        metrics = business_metrics.compute(
            _session(tmp_path, [_snapshot(i, value=i * 100) for i in range(1, 101)]), 0,
        )
        assert metrics.value_at_25pct < metrics.value_at_50pct < metrics.value_at_75pct

    def test_days_to_first_profit_is_measured_from_the_start(self, tmp_path: Path) -> None:
        metrics = business_metrics.compute(_session(tmp_path, [
            _snapshot(1000, income=0, expenses=-50),
            _snapshot(1100, income=100, expenses=-500),
            _snapshot(1200, income=900, expenses=-500),
        ]), 0)
        assert metrics.days_to_first_profit == 200

    def test_never_turning_a_profit_is_not_zero_days(self, tmp_path: Path) -> None:
        """Zero would read as profitable immediately, which is the opposite."""
        metrics = business_metrics.compute(_session(tmp_path, [
            _snapshot(1, income=100, expenses=-500),
        ]), 0)
        assert metrics.days_to_first_profit == -1


class TestCapitalEfficiency:
    def test_return_is_measured_against_capital_commanded(self, tmp_path: Path) -> None:
        metrics = business_metrics.compute(_session(tmp_path, [
            _snapshot(1, value=0, money=100_000, loan=100_000),
            _snapshot(2, value=200_000, money=50_000, loan=100_000),
        ]), 0)
        assert metrics.peak_capital_deployed == 200_000
        assert metrics.return_on_capital == 1.0

    def test_a_large_starting_balance_is_not_credited_as_growth(self, tmp_path: Path) -> None:
        """Value gained is measured from the start, so being handed money is not an
        achievement."""
        metrics = business_metrics.compute(_session(tmp_path, [
            _snapshot(1, value=500_000, money=100_000),
            _snapshot(2, value=500_000, money=100_000),
        ]), 0)
        assert metrics.return_on_capital == 0.0


class TestOperations:
    def test_it_counts_only_this_company(self, tmp_path: Path) -> None:
        """A rival's vehicles must not flatter the contestant's utilisation."""
        session = tmp_path / "ses_test"
        session.mkdir()
        payload = {
            "companies": [{"id": 0, "value": 1, "q0_cargo": 100}],
            "vehicles": [
                {"id": 1, "company_id": 0, "profit_this_year": 50},
                {"id": 2, "company_id": 1, "profit_this_year": 50},
                {"id": 3, "company_id": 1, "profit_this_year": 50},
            ],
            "stations": [{"id": 1, "company_id": 0}, {"id": 2, "company_id": 1}],
            "infrastructure": [],
        }
        pq.write_table(
            pa.Table.from_pylist(
                [{"game_date": 1, "snapshot_json": json.dumps(payload)}],
                schema=pa.schema([
                    ("game_date", pa.int32()), ("snapshot_json", pa.large_string()),
                ]),
            ),
            session / "snapshots.parquet",
        )
        metrics = business_metrics.compute(session, 0)
        assert metrics.vehicles_final == 1
        assert metrics.stations_final == 1
        assert metrics.cargo_per_vehicle == 100.0

    def test_idle_means_parked_not_merely_in_a_depot(self, tmp_path: Path) -> None:
        """A vehicle passing through a depot for servicing is working."""
        metrics = business_metrics.compute(_session(tmp_path, [_snapshot(1, vehicles=[
            {"company_id": 0, "in_depot": True, "running": False, "profit_this_year": 0},
            {"company_id": 0, "in_depot": True, "running": True, "profit_this_year": 10},
            {"company_id": 0, "in_depot": False, "running": True, "profit_this_year": 10},
            {"company_id": 0, "in_depot": False, "running": True, "profit_this_year": -5},
        ])]), 0)
        assert metrics.idle_vehicle_share == 0.25
        assert metrics.profitable_vehicle_share == 0.5


class TestDecisionEconomy:
    def test_cost_per_point_needs_both_a_cost_and_a_score(self, tmp_path: Path) -> None:
        """An unreported spend must not read as free. It stays zero, which the board
        renders blank rather than as a dollar amount."""
        session = _session(tmp_path, [_snapshot(1, value=1000)])
        priced = business_metrics.compute(
            session, 0, primary_score=500, total_cost_usd=10.0,
        )
        assert priced.usd_per_score_point == 0.02

        unreported = business_metrics.compute(session, 0, primary_score=500)
        assert unreported.usd_per_score_point == 0.0

    def test_action_rate_and_value_per_action(self, tmp_path: Path) -> None:
        metrics = business_metrics.compute(
            _session(tmp_path, [_snapshot(1, value=1000)]), 0,
            total_actions=50, successful_actions=40,
        )
        assert metrics.action_success_rate == 0.8
        assert metrics.value_per_action == 20.0


class TestItDoesNotBreakARun:
    def test_missing_snapshots_leave_empty_metrics(self, tmp_path: Path) -> None:
        """A run whose snapshots did not survive still has a score worth recording. A
        result row that fails to write is worse than one with empty columns."""
        empty = tmp_path / "ses_empty"
        empty.mkdir()
        metrics = business_metrics.compute(empty, 0, primary_score=500)
        assert metrics.operating_margin_final == 0.0
        assert metrics.metrics_version == business_metrics.METRICS_VERSION

    def test_a_company_absent_from_the_snapshots_is_handled(self, tmp_path: Path) -> None:
        metrics = business_metrics.compute(_session(tmp_path, [_snapshot(1, value=5)]), 7)
        assert metrics.vehicles_final == 0

    def test_unreadable_snapshots_do_not_raise(self, tmp_path: Path) -> None:
        session = tmp_path / "ses_bad"
        session.mkdir()
        (session / "snapshots.parquet").write_text("not parquet")
        assert business_metrics.compute(session, 0).operating_margin_final == 0.0


class TestAgainstRealRecordedSessions:
    """Synthetic snapshots prove the arithmetic. These prove the reader matches what
    the recorder actually writes, which is the part a fixture cannot tell me."""

    def _sessions(self) -> list[Path]:
        root = Path(__file__).parent.parent / "logs" / "sessions"
        if not root.exists():
            return []
        return [d for d in sorted(root.iterdir()) if (d / "snapshots.parquet").exists()]

    def test_it_reads_a_real_session_without_error(self) -> None:
        sessions = self._sessions()
        if not sessions:
            pytest.skip("no recorded sessions in this checkout")
        for session in sessions[:5]:
            metrics = business_metrics.compute(session, 0)
            assert metrics.metrics_version == business_metrics.METRICS_VERSION

    def test_a_real_session_yields_something(self) -> None:
        """Guards against the reader silently matching nothing, which would return
        zeroes that look like a legitimately quiet run."""
        sessions = self._sessions()
        if not sessions:
            pytest.skip("no recorded sessions in this checkout")
        assert any(
            business_metrics.compute(s, 0).min_cash != 0 for s in sessions
        ), "no recorded session produced a single non-zero metric"


def test_every_metric_reaches_the_result_schema() -> None:
    """A metric computed and then dropped by the schema is worse than one not
    computed: it looks present in the code and is absent from the artifact."""
    from dataclasses import fields

    from nttd.store.result_writer import _SCHEMA

    for spec in fields(business_metrics.BusinessMetrics):
        assert spec.name in _SCHEMA.names, spec.name


class TestReadingAnOlderResult:
    """Every result written before a column existed is missing it, and readers index
    rows directly. `nttd result` raised KeyError: 'final_save_digest' on a session from
    two days earlier, and adding twenty-eight metric columns made every existing file
    old in the same way. A board ingesting bundles across nttd versions would hit this
    constantly.
    """

    def _old_result(self, tmp_path: Path) -> Path:
        """A result file with only the columns that existed early on."""
        session = tmp_path / "ses_old"
        session.mkdir()
        schema = pa.schema([
            ("session_id", pa.string()),
            ("company_id", pa.int16()),
            ("company_name", pa.string()),
            ("primary_score", pa.int32()),
        ])
        pq.write_table(
            pa.Table.from_pylist(
                [{"session_id": "ses_old", "company_id": 0,
                  "company_name": "Old Ltd", "primary_score": 300}],
                schema=schema,
            ),
            session / "result.parquet",
        )
        return session

    def test_missing_columns_are_filled_rather_than_absent(self, tmp_path: Path) -> None:
        from nttd.store.result_writer import _SCHEMA, read_result

        rows = read_result(self._old_result(tmp_path))
        assert rows
        for name in _SCHEMA.names:
            assert name in rows[0], name

    def test_the_defaults_are_typed(self, tmp_path: Path) -> None:
        """A reader formatting a number must not meet None."""
        from nttd.store.result_writer import read_result

        row = read_result(self._old_result(tmp_path))[0]
        assert row["operating_margin_final"] == 0.0
        assert row["vehicles_final"] == 0
        assert row["ended_in_debt"] is False
        assert row["metrics_version"] == ""

    def test_what_was_recorded_is_untouched(self, tmp_path: Path) -> None:
        from nttd.store.result_writer import read_result

        row = read_result(self._old_result(tmp_path))[0]
        assert row["primary_score"] == 300
        assert row["company_name"] == "Old Ltd"

    def test_the_cli_says_there_are_no_metrics_rather_than_showing_zeros(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Zeros are a claim. "days to first profit: 0" says profitable immediately,
        when the truth is that nobody measured."""
        from nttd.cli.result_command import _print_business_metrics
        from nttd.store.result_writer import read_result

        _print_business_metrics(read_result(self._old_result(tmp_path)))
        output = capsys.readouterr().out
        assert "No business metrics" in output
        assert "days to first profit" not in output
