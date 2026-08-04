"""Telemetry for one decision cycle of a contestant's loop.

These survive from the deleted server-driven gameloop, where nttd ran the
contestant's agent and could time every phase itself. In the client-driven model the
contestant owns the loop, so nttd cannot observe a cycle unless the contestant
reports it: these are the shape of that report, and of the ``agent_cycles.parquet``
rows written from it.

That makes the distinction in the data honest. Anything nttd derives from its own
records -- action counts and outcomes, from ``actions.parquet`` -- is observed.
Anything here that only the contestant's process can know, above all token counts
and cost, is reported. A leaderboard should present the two with different
confidence, and cannot if they share a home.
"""

from __future__ import annotations

from pydantic import BaseModel


class TokenUsage(BaseModel):
    """LLM spend for a single decision.

    Contestant-reported. nttd runs no model in the client-driven design, so it has
    no independent view of these numbers and must not present them as verified.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    model: str = ""
    provider: str = ""


class CycleRecord(BaseModel):
    """One decision cycle, as reported by the contestant's loop.

    ``connection_id`` identifies the reporting loop within a session. It is a label
    for grouping telemetry, not a credential: the company an action affects is
    decided by the participant token, never by anything in here.
    """

    connection_id: str
    session_id: str
    cycle_number: int
    game_date: int = 0
    observe_ms: float = 0.0
    decide_ms: float = 0.0
    execute_ms: float = 0.0
    total_ms: float = 0.0
    actions_proposed: int = 0
    actions_executed: int = 0
    actions_succeeded: int = 0
    actions_failed: int = 0
    observation_size_bytes: int = 0
    balance: int = 0
    income: int = 0
    company_value: int = 0
    balance_delta: int = 0
    vehicles_running: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    llm_model: str = ""
    llm_provider: str = ""
