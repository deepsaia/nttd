"""What a contestant tells nttd about itself.

nttd runs no agent, so it cannot observe a model name, a token count, or a dollar
cost -- those live in the contestant's process. It records what it is told and marks
the whole group as reported rather than observed, because a leaderboard that ranks on
cost needs to know which numbers it can trust.

Spend is PER MODEL, not a single figure. A multi-agent system routinely uses several:
neuro-san runs a front-man plus specialists and commonly gives them different models,
so a cheap router in front of one expensive planner has a very different cost profile
from the same total spent uniformly. Collapsing that into one string would throw away
the thing that makes a MAS entry interesting, and would force a contestant to invent a
name like "gpt-5.2+haiku-4.5" that nothing could aggregate.

Nothing here is required. A contestant that reports nothing still gets a complete
result row: action counts and outcomes come from nttd's own audit log.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelSpend(BaseModel):
    """Tokens and cost attributed to one model.

    Attributes:
        model: The model identifier, as the provider names it.
        role: What this model did in the system -- "front_man", "route_planner",
            "validator". Optional, and free-form on purpose: nttd has no view into a
            contestant's topology and should not impose a vocabulary on it. Two
            entries may name the same model in different roles, which is why role is
            part of the key rather than a label.
        prompt_tokens: Input tokens consumed by this model.
        completion_tokens: Output tokens produced by this model.
        total_cost_usd: What this model cost, or None when the tokens are known and the
            price is not. Those are different claims and one number cannot say both.
            Omitting it means "I do not know"; sending 0.0 means "this was free", which a
            local policy may say truthfully and a hosted model may not.

            The case this exists for: a framework that counts tokens against its own price
            table and finds no entry for the model. neuro-san logs a warning and falls back
            to a cost of zero, so a runner passing that figure straight through would
            publish a free run. Reporting the tokens and withholding the price is honest;
            reporting a zero it was handed is not.
    """

    model: str
    role: str = ""
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float | None = Field(default=None, ge=0.0)


class SpendReport(BaseModel):
    """A contestant's declaration of its identity and spend.

    Every field is optional. Merged into whatever was reported before, so a runner may
    declare its framework at the start and its spend at the end rather than holding
    everything until it can send one complete message.

    Attributes:
        nttd_framework: What drove the loop -- langchain, neuro-san, a custom policy.
        agent_id: A label for the loop, useful when several share a company.
        participant_type: What kind of entry this is. Left to the contestant because
            nttd genuinely cannot tell an RL policy from a scripted one by watching
            its actions.
        models: Per-model spend. Repeated calls merge by (model, role), adding
            tokens and cost, so a runner may report incrementally per cycle instead
            of accumulating totals itself.
    """

    nttd_framework: str = ""
    agent_id: str = ""
    participant_type: str = ""
    models: list[ModelSpend] = Field(default_factory=list)
