"""Turns a GameScript reply into an ActionResult.

One function, called from both places an action can run: the REST submission and the
stepped flush. They each had their own copy of this mapping, which is how the stepped
path came to know nothing about partial builds or error codes while the REST path did.
The same divergence had already happened once with the admission check.

The GameScript answers with ``success``, an optional ``result``, and on refusal an
``error`` plus, when OpenTTD was the one refusing, ``error_code`` and ``error_category``.
"""

from __future__ import annotations

from typing import Any

from nttd.config import error_codes
from nttd.schemas.action_result import ActionResult, ActionStatus


def result_from_reply(action_id: str, reply: dict[str, Any]) -> ActionResult:
    """Read one GameScript reply.

    A compound build that laid part of a route reports PARTIAL rather than FAILED: the
    world moved and was paid for, so calling it a plain failure loses that, and calling
    it a success would claim a route that has a gap in it.
    """
    payload = reply.get("result") or {}

    if reply.get("success"):
        return ActionResult(
            action_id=action_id,
            status=ActionStatus.SUCCESS,
            changed_entities=payload,
        )

    code = reply.get("error_code")
    return ActionResult(
        action_id=action_id,
        status=(
            ActionStatus.PARTIAL
            if payload.get("status") == "partial"
            else ActionStatus.FAILED
        ),
        error=_explain(reply),
        # Present only when OpenTTD refused. nttd's own precondition failures carry no
        # code, and that absence is how the two are told apart.
        error_code=code,
        error_name=error_codes.error_name(code),
        error_category=error_codes.category_name(reply.get("error_category")),
        # A failed compound build still changed the world, so what it managed comes back
        # with the failure rather than being dropped.
        changed_entities=payload,
    )


def _explain(reply: dict[str, Any]) -> str:
    """The refusal, in words an agent can act on.

    OpenTTD maps a failure to a named ScriptError only when the underlying CommandCost
    carries a string it recognises. Everything else arrives as ERR_UNKNOWN, which is most
    refusals in practice and is the one answer nothing can be done with. A run once spent
    two of its five actions re-submitting a build onto its own station, because the
    refusal did not say the tiles were taken.

    So the GameScript inspects the world on the failure path and sends a ``reason`` when
    it can work one out. It leads, because it is the part worth reading; the game's own
    wording follows so nothing is lost and an operator can still match it to OpenTTD.
    """
    error = reply.get("error")
    reason = reply.get("reason")
    if not reason:
        return error or "GS returned failure"
    if not error or error == reason:
        return str(reason)
    return f"{reason} (the game reported: {error})"
