"""Refuses game-mutating operator operations during a scored session.

One helper so every guarded route reports a refusal the same way, and so the list
of what is guarded is not spread across route bodies.

See ``nttd.runtime.scored_lock`` for why this is session state rather than a
credential check.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from nttd.runtime.session_runtime import SessionRuntime
from nttd.schemas.action_result import ActionStatus

logger = logging.getLogger(__name__)


def require_unscored(
    runtime: SessionRuntime, operation: str, detail: str = "",
) -> None:
    """Raise 403 if this session is scored.

    The refusal is recorded on the session's lock first, so the attempt appears in
    the result record even though nothing happened.

    Args:
        runtime: The session being acted on.
        operation: Stable name for the refused operation, e.g. ``deity/found_town``.
            Recorded, so keep it consistent rather than descriptive.
        detail: Extra context for the audit trail, e.g. the GS action attempted.
    """
    game_date = runtime.world.game.game_date
    if runtime.scored_lock.check(operation, game_date=game_date, detail=detail):
        return

    # Also record it as an action so it lands in actions.parquet alongside real
    # actions, rather than in a separate channel a reviewer has to know about.
    _record_blocked(runtime, operation, detail, game_date)

    raise HTTPException(
        status_code=403,
        detail=(
            f"{operation} is refused: this session is scored. Operator operations "
            f"that mutate the game are unavailable for the whole run, for every "
            f"caller, so a scored result cannot be invalidated by accident. The "
            f"attempt has been recorded. Start an unscored session for scenario "
            f"authoring or debugging."
        ),
    )


def _record_blocked(
    runtime: SessionRuntime, operation: str, detail: str, game_date: int,
) -> None:
    """Write the refused attempt into the session's action log."""
    recorder = getattr(runtime, "recorder", None)
    if recorder is None:
        return

    from nttd.schemas.action_envelope import ActionEnvelope, ActionMode
    from nttd.schemas.action_result import ActionResult

    try:
        envelope = ActionEnvelope(
            action_id=f"blocked_{len(runtime.scored_lock.blocked)}",
            company_id=-1,
            action_type=operation,
            parameters={"detail": detail} if detail else {},
            mode=ActionMode.ATOMIC,
            metadata={"game_date": game_date, "participant_id": "operator"},
        )
        recorder.record_action(
            envelope,
            ActionResult(
                action_id=envelope.action_id,
                status=ActionStatus.BLOCKED,
                error="refused: session is scored",
            ),
        )
    except Exception:
        # Recording is for the audit trail; failing to record must not turn a
        # clean refusal into a server error.
        logger.exception("Could not record blocked attempt %s", operation)
