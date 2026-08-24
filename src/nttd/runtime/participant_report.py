"""Per-company contestant detail for the result record.

This replaces the deleted gameloop's ``participant_summary``, and the replacement is
not equivalent, deliberately. When nttd ran the contestant's agent in-process it
could see every LLM call and time every phase. In the client-driven model the
contestant runs its own loop in its own process, so nttd's knowledge splits in two
and the record should say which half a number came from:

  * OBSERVED. Action counts and outcomes, tallied from ``actions.parquet`` -- nttd's
    own audit log, written as each action arrives. A contestant cannot inflate these
    without submitting the actions, and submitting them means passing the budget and
    the allowlist. So they are as trustworthy as the run itself.

  * REPORTED. Framework, token counts, cost. Only the contestant's process can know
    these, and they arrive through ``POST /report``. nttd records what it was told and
    flags it, because presenting it with the same confidence as observed counts would
    be a lie about provenance -- and a leaderboard that ranks on cost needs the
    difference.

Spend is kept PER MODEL. A multi-agent system routinely uses several: neuro-san runs
a front-man plus specialists, often on different models, so a cheap router in front of
one expensive planner has a very different profile from the same total spent
uniformly. The totals are rolled up for the result row, and the breakdown is kept so a
board can show it.

A contestant that reports nothing still gets a complete row: the observed half is
always present, because it comes from nttd's records rather than the contestant's
cooperation.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_IDENTITY_FIELDS = ("nttd_framework", "agent_id", "participant_type")


class ParticipantReport:
    """Accumulates per-company contestant detail over a session.

    Keyed by company_id, since scoring is per company and several contestant loops may
    legitimately share one.
    """

    def __init__(self) -> None:
        # Contestant-declared identity, keyed by company_id.
        self._identity: dict[int, dict[str, str]] = {}
        # Per-model spend, keyed by company_id then (model, role). Two entries may
        # name the same model in different roles, so the role is part of the key.
        self._spend: dict[int, dict[tuple[str, str], dict[str, float]]] = {}

    def declare(self, company_id: int, **fields: Any) -> None:
        """Record what a contestant says about itself.

        Identity fields are replaced; per-model spend is ADDED. Adding rather than
        replacing lets a runner report each cycle's usage as it goes instead of
        accumulating totals itself, which is the natural shape for a loop that already
        gets per-call usage back from its provider.

        Unverified by construction: nttd has no way to check any of it, which is why
        the result marks the whole group as reported.
        """
        identity = self._identity.setdefault(company_id, {})
        for field in _IDENTITY_FIELDS:
            value = fields.get(field)
            if value:
                identity[field] = str(value)

        for entry in fields.get("models") or []:
            self._add_model_spend(company_id, entry)

    def _add_model_spend(self, company_id: int, entry: Any) -> None:
        """Accumulate one model's usage."""
        raw = entry if isinstance(entry, dict) else entry.model_dump()
        model = str(raw.get("model") or "").strip()
        if not model:
            logger.warning("Ignoring a spend entry with no model name")
            return
        key = (model, str(raw.get("role") or ""))
        bucket = self._spend.setdefault(company_id, {}).setdefault(
            key,
            {
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
                "total_cost_usd": 0.0,
                # Whether the price has ever been stated for this model. A contestant may
                # know its token counts and not its cost, and adding an absent price as
                # zero would turn "I do not know" into "it was free".
                "priced": False,
            },
        )
        for field in ("prompt_tokens", "completion_tokens"):
            try:
                bucket[field] += float(raw.get(field) or 0)
            except (TypeError, ValueError):
                logger.warning("Ignoring non-numeric %s=%r", field, raw.get(field))

        cost = raw.get("total_cost_usd")
        if cost is None:
            return
        try:
            bucket["total_cost_usd"] += float(cost)
        except (TypeError, ValueError):
            logger.warning("Ignoring non-numeric total_cost_usd=%r", cost)
            return
        bucket["priced"] = True

    def model_breakdown(self, company_id: int) -> list[dict[str, Any]]:
        """Per-model spend for a company, for the record and for a board to show."""
        return [
            {
                "model": model,
                "role": role,
                "prompt_tokens": int(totals["prompt_tokens"]),
                "completion_tokens": int(totals["completion_tokens"]),
                "total_cost_usd": (
                    round(totals["total_cost_usd"], 6) if totals["priced"] else None
                ),
            }
            for (model, role), totals in sorted(self._spend.get(company_id, {}).items())
        ]

    def build(
        self, action_counts: dict[int, dict[str, int]] | None = None,
    ) -> dict[int, dict[str, Any]]:
        """Return per-company detail for ``ResultWriter.write(participants=...)``.

        Args:
            action_counts: Observed tallies from ``SessionRecorder.action_counts()``,
                keyed by company_id. The recorder counts as it writes, so these cover
                the whole session rather than whatever remained unflushed.

        A company appears if it either declared something or took an action, so a
        contestant that connected and did nothing still gets a row, and one that
        played without declaring anything gets its observed counts.
        """
        companies = set(self._identity) | set(self._spend) | set(action_counts or {})
        summary: dict[int, dict[str, Any]] = {}

        for company_id in companies:
            entry = self._blank()
            entry.update(self._identity.get(company_id, {}))

            breakdown = self.model_breakdown(company_id)
            if breakdown:
                # A single "model" column still has to say something, and the honest
                # summary of a multi-model system is every model that ran, not the
                # first or the most expensive.
                entry["model"] = "+".join(
                    sorted({item["model"] for item in breakdown}),
                )
                entry["prompt_tokens"] = sum(i["prompt_tokens"] for i in breakdown)
                entry["completion_tokens"] = sum(i["completion_tokens"] for i in breakdown)
                # A total only means anything if every model in it was priced. One model
                # missing a price makes the sum a partial figure that still reads as a
                # total, which is a worse answer than declining to give one.
                priced = [i["total_cost_usd"] for i in breakdown]
                entry["cost_is_reported"] = all(cost is not None for cost in priced)
                entry["total_cost"] = (
                    round(sum(priced), 6) if entry["cost_is_reported"] else 0.0
                )
                entry["spend_is_reported"] = True
                entry["model_breakdown"] = breakdown

            counts = (action_counts or {}).get(company_id) or {}
            entry["total_actions"] = counts.get("total_actions", 0)
            entry["successful_actions"] = counts.get("successful_actions", 0)
            summary[company_id] = entry

        return summary

    @staticmethod
    def _blank() -> dict[str, Any]:
        return {
            "participant_type": "agent",
            "agent_id": "",
            "nttd_framework": "",
            "model": "",
            # Observed: tallied from nttd's own action log.
            "total_actions": 0,
            "successful_actions": 0,
            # Reported. spend_is_reported distinguishes "the contestant told us zero"
            # from "the contestant told us nothing", which a reader comparing a free
            # RL policy against an unreported MAS entry needs.
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_cost": 0.0,
            # Separate from spend_is_reported, because tokens and price are separate
            # claims: a run can be counted and unpriced.
            "cost_is_reported": False,
            "spend_is_reported": False,
            "model_breakdown": [],
        }
