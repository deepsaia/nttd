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

  * REPORTED. Model name, framework, token counts, cost. Only the contestant's
    process can know these. nttd records what it was told and marks it unverified;
    presenting them with the same confidence as observed counts would be a lie about
    provenance, and a leaderboard that ranks on cost needs to know the difference.

A contestant that reports nothing still gets a complete row: the observed half is
always present, because it comes from nttd's records rather than the contestant's
cooperation.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ParticipantReport:
    """Accumulates per-company contestant detail over a session.

    Attributes are keyed by company_id, since scoring is per company and several
    contestant loops may legitimately share one.
    """

    def __init__(self) -> None:
        # Contestant-declared identity and spend, keyed by company_id.
        self._declared: dict[int, dict[str, Any]] = {}

    def declare(self, company_id: int, **fields: Any) -> None:
        """Record what a contestant says about itself.

        Merged rather than replaced, so a contestant may declare its model at the
        start and its token totals at the end. Later values win for the same key.

        Unverified by construction: nttd has no way to check any of it, which is why
        the result marks the whole group as reported.
        """
        entry = self._declared.setdefault(company_id, {})
        entry.update({key: value for key, value in fields.items() if value not in (None, "")})

    def build(
        self, action_counts: dict[int, dict[str, int]] | None = None,
    ) -> dict[int, dict[str, Any]]:
        """Return per-company detail for ``ResultWriter.write(participants=...)``.

        Args:
            action_counts: Observed tallies from ``SessionRecorder.action_counts()``,
                keyed by company_id. The recorder counts as it writes, so these
                cover the whole session rather than whatever remained unflushed.

        A company appears if it either declared something or took an action, so a
        contestant that connected and did nothing still gets a row, and one that
        played without declaring anything gets its observed counts.
        """
        summary: dict[int, dict[str, Any]] = {}

        for company_id, declared in self._declared.items():
            summary[company_id] = self._blank() | declared

        for company_id, counts in (action_counts or {}).items():
            entry = summary.setdefault(int(company_id), self._blank())
            entry["total_actions"] = counts.get("total_actions", 0)
            entry["successful_actions"] = counts.get("successful_actions", 0)

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
            # Reported: only the contestant's process can know these. Zero means
            # "not reported", which the result distinguishes from a verified zero
            # through the counts_are_reported flag.
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_cost": 0.0,
            "cost_is_estimated": False,
        }
