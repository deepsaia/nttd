"""Tests for token accounting: cost estimation, report generation, and pipeline integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import polars as pl

from nttd.analysis.reports.token_accounting import generate
from nttd.analysis.token_costs import estimate_cost
from nttd.schemas.cycle_record import TokenUsage


class TestTokenUsage:
    def test_defaults_to_zero(self) -> None:
        usage = TokenUsage()
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0
        assert usage.total_cost == 0.0
        assert usage.model == ""
        assert usage.provider == ""

    def test_sets_all_fields(self) -> None:
        usage = TokenUsage(
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            total_cost=0.005, model="gpt-4o", provider="openai",
        )
        assert usage.prompt_tokens == 100
        assert usage.total_tokens == 150
        assert usage.model == "gpt-4o"


class TestEstimateCost:
    def test_known_model_exact_match(self) -> None:
        cost = estimate_cost("gpt-4o", 1_000_000, 1_000_000)
        assert cost == 2.50 + 10.00

    def test_known_model_prefix_match(self) -> None:
        cost = estimate_cost("gpt-4o-2024-08-06", 1_000_000, 0)
        assert cost == 2.50

    def test_unknown_model_returns_zero(self) -> None:
        cost = estimate_cost("some-unknown-model", 1000, 500)
        assert cost == 0.0

    def test_zero_tokens_returns_zero(self) -> None:
        cost = estimate_cost("gpt-4o", 0, 0)
        assert cost == 0.0

    def test_anthropic_model(self) -> None:
        cost = estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert cost == 3.00 + 15.00


def _make_session(
    agent_cycles_data: list[dict],
    session_id: str = "ses_test",
    name: str = "test",
    model: str = "gpt-4o",
) -> MagicMock:
    """Create a mock SessionData with the given agent_cycles."""
    session = MagicMock()
    session.session_id = session_id
    session.name = name
    session.model = model
    session.session_dir = Path("/tmp/test")
    session.agent_cycles = pl.DataFrame(agent_cycles_data)
    session.agents = {}
    return session


class TestTokenAccountingReport:
    def test_basic_report(self) -> None:
        cycles = [
            {
                "connection_id": "s:0:rail_agent",
                "cycle_number": 1,
                "game_date": 100,
                "observe_ms": 10.0,
                "decide_ms": 50.0,
                "execute_ms": 5.0,
                "total_ms": 65.0,
                "actions_proposed": 2,
                "actions_executed": 2,
                "actions_succeeded": 1,
                "actions_failed": 1,
                "observation_size_bytes": 500,
                "balance": 100000,
                "income": 5000,
                "company_value": 200000,
                "balance_delta": 5000,
                "vehicles_running": 3,
                "prompt_tokens": 500,
                "completion_tokens": 200,
                "total_tokens": 700,
                "total_cost": 0.005,
                "llm_model": "gpt-4o",
                "llm_provider": "openai",
            },
            {
                "connection_id": "s:0:rail_agent",
                "cycle_number": 2,
                "game_date": 110,
                "observe_ms": 10.0,
                "decide_ms": 50.0,
                "execute_ms": 5.0,
                "total_ms": 65.0,
                "actions_proposed": 3,
                "actions_executed": 3,
                "actions_succeeded": 3,
                "actions_failed": 0,
                "observation_size_bytes": 600,
                "balance": 105000,
                "income": 5000,
                "company_value": 210000,
                "balance_delta": 5000,
                "vehicles_running": 4,
                "prompt_tokens": 600,
                "completion_tokens": 250,
                "total_tokens": 850,
                "total_cost": 0.006,
                "llm_model": "gpt-4o",
                "llm_provider": "openai",
            },
        ]
        session = _make_session(cycles)
        result = generate([session])

        assert result.name == "token_accounting"
        assert len(result.data["per_agent"]) == 1

        agent = result.data["per_agent"][0]
        assert agent["agent_id"] == "rail_agent"
        assert agent["total_prompt_tokens"] == 1100
        assert agent["total_completion_tokens"] == 450
        assert agent["total_tokens"] == 1550
        assert agent["model"] == "gpt-4o"
        assert agent["provider"] == "openai"
        assert agent["cycles"] == 2

        totals = result.data["session_totals"]
        assert totals["total_tokens"] == 1550
        assert totals["total_cycles"] == 2

        assert "gpt-4o" in result.markdown
        assert "openai" in result.markdown

    def test_no_token_data(self) -> None:
        cycles = [
            {
                "connection_id": "s:0:agent",
                "cycle_number": 1,
                "game_date": 100,
                "observe_ms": 10.0,
                "decide_ms": 50.0,
                "execute_ms": 5.0,
                "total_ms": 65.0,
                "actions_proposed": 1,
                "actions_executed": 1,
                "actions_succeeded": 1,
                "actions_failed": 0,
                "observation_size_bytes": 500,
                "balance": 100000,
                "income": 5000,
                "company_value": 200000,
                "balance_delta": 5000,
                "vehicles_running": 1,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "total_cost": 0.0,
                "llm_model": "",
                "llm_provider": "",
            },
        ]
        session = _make_session(cycles)
        result = generate([session])
        assert "No token data" in result.markdown

    def test_multiple_agents(self) -> None:
        cycles = [
            {
                "connection_id": "s:0:rail_agent",
                "cycle_number": 1, "game_date": 100,
                "observe_ms": 0, "decide_ms": 0, "execute_ms": 0, "total_ms": 0,
                "actions_proposed": 0, "actions_executed": 0,
                "actions_succeeded": 0, "actions_failed": 0,
                "observation_size_bytes": 0,
                "balance": 0, "income": 0, "company_value": 0,
                "balance_delta": 0, "vehicles_running": 0,
                "prompt_tokens": 1000, "completion_tokens": 500,
                "total_tokens": 1500, "total_cost": 0.01,
                "llm_model": "gpt-4o", "llm_provider": "openai",
            },
            {
                "connection_id": "s:0:road_agent",
                "cycle_number": 1, "game_date": 100,
                "observe_ms": 0, "decide_ms": 0, "execute_ms": 0, "total_ms": 0,
                "actions_proposed": 0, "actions_executed": 0,
                "actions_succeeded": 0, "actions_failed": 0,
                "observation_size_bytes": 0,
                "balance": 0, "income": 0, "company_value": 0,
                "balance_delta": 0, "vehicles_running": 0,
                "prompt_tokens": 800, "completion_tokens": 300,
                "total_tokens": 1100, "total_cost": 0.007,
                "llm_model": "claude-sonnet-4-6", "llm_provider": "anthropic",
            },
        ]
        session = _make_session(cycles)
        result = generate([session])

        assert len(result.data["per_agent"]) == 2
        totals = result.data["session_totals"]
        assert totals["total_tokens"] == 2600
        assert totals["total_cycles"] == 2

    def test_empty_sessions(self) -> None:
        session = _make_session([])
        result = generate([session])
        assert "No token data" in result.markdown

    def test_figures_created(self) -> None:
        cycles = [
            {
                "connection_id": "s:0:agent",
                "cycle_number": 1, "game_date": 100,
                "observe_ms": 0, "decide_ms": 0, "execute_ms": 0, "total_ms": 0,
                "actions_proposed": 0, "actions_executed": 0,
                "actions_succeeded": 0, "actions_failed": 0,
                "observation_size_bytes": 0,
                "balance": 0, "income": 0, "company_value": 0,
                "balance_delta": 0, "vehicles_running": 0,
                "prompt_tokens": 100, "completion_tokens": 50,
                "total_tokens": 150, "total_cost": 0.001,
                "llm_model": "gpt-4o", "llm_provider": "openai",
            },
        ]
        session = _make_session(cycles)
        result = generate([session])
        assert len(result.figures) == 2
        assert result.figures[0][0] == "token_usage_by_agent"
        assert result.figures[1][0] == "tokens_over_time"
