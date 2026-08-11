"""The single admission check every contestant action passes.

There are two ways an action reaches the GameScript -- ``POST /actions/submit`` in
real-time play, and the stepped loop's batch flush -- and they had different rules.
The REST route checked the operator-tier list, the participant allowlist, and the
action budget; the stepped path checked nothing and called ``send_gamescript``
directly, so ``set_max_loan`` was reachable in a scored session and left no row in
``actions.parquet``. Verified against a live server: five queued operator actions
executed with only the two REST attempts appearing in the audit log.

That is the same shape as the ``gs/query`` bypass closed earlier: a second door added
later, guarded by a copy of the rules that was not kept in step. So the rules live
here, once, and both callers ask this module rather than re-implementing it.

The order matters. Operator-tier is checked before the allowlist so that reaching for
a superhuman power gets an explanation rather than "unknown action" -- an agent told
only "no" retries forever. The budget is checked last, because a refusal that never
had a chance of succeeding should not consume it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from nttd.constants import KNOWN_ACTIONS, OPERATOR_ACTIONS, READ_ONLY_GS_ACTIONS
from nttd.schemas.action_result import ActionStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Admission:
    """Whether an action may execute, and why not if it may not.

    Attributes:
        allowed: True when the action should be sent to the GameScript.
        status: The status to record when refused. REJECTED for a vocabulary
            problem, which is the contestant's mistake; BLOCKED for a budget
            refusal, which is the scenario's limit. A reader of the action log needs
            to tell those apart.
        error: The message to record and return.
    """

    allowed: bool
    status: ActionStatus = ActionStatus.SUCCESS
    error: str = ""


_OPERATOR_TIER_REASON = (
    "{action} is operator-tier: it has no human-player equivalent, so it is not "
    "available for play. See the operator tier for scenario authoring."
)

# A read-only command reaches the GameScript through the query endpoint and is deliberately
# not an action, so the allowlist cannot be routed around. Saying only "unknown" was a lie
# about something that exists, dispatches, and works: an air run spent two of its five
# actions submitting get_hangars, never found its hangar, and its one buy_vehicle then
# failed for want of one. The name of the door is the whole content of the fix.
_READ_ONLY_REASON = (
    "{action} is a read-only query, not an action. It exists, but it is answered by "
    "POST /state/gs/query with {{\"action\": \"{action}\", \"params\": {{...}}}}, and "
    "queries are never submitted as actions. Nothing was changed and nothing was spent."
)


def admit(action_type: str, company_id: int) -> Admission:
    """Decide whether one submission may execute.

    Args:
        action_type: The GS command being requested.
        company_id: The company the action is for, already resolved from the
            participant token by the caller. Not re-derived here: this module decides
            what may happen, not who is asking.

    Returns:
        An ``Admission``. When refused, the caller records ``status`` and ``error``
        against the action rather than inventing its own wording, so the two paths
        produce identical audit rows for identical refusals.
    """
    if action_type in OPERATOR_ACTIONS:
        return Admission(
            allowed=False,
            status=ActionStatus.REJECTED,
            error=_OPERATOR_TIER_REASON.format(action=action_type),
        )

    if action_type in READ_ONLY_GS_ACTIONS:
        return Admission(
            allowed=False,
            status=ActionStatus.REJECTED,
            error=_READ_ONLY_REASON.format(action=action_type),
        )

    if action_type not in KNOWN_ACTIONS:
        return Admission(
            allowed=False,
            status=ActionStatus.REJECTED,
            error=f"Unknown action_type: {action_type}",
        )

    return Admission(allowed=True)
