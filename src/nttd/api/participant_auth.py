"""Resolves a participant token into the company an action may act as.

Every action path routes its company_id through here. The value a caller supplies
is never trusted: it is overwritten with the company the presented token owns.

Backwards compatibility: when a session has issued no tokens, the caller's
company_id is accepted. Existing scenarios, the examples, and the admin console
all predate tokens and would otherwise break. A scored session issues tokens, so
the permissive path does not apply where it matters.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import Header, HTTPException

from nttd.runtime.session_runtime import SessionRuntime

logger = logging.getLogger(__name__)

# Header carrying the participant token. Also accepted as `Authorization: Bearer`.
TOKEN_HEADER = "X-Participant-Token"

ParticipantToken = Annotated[str | None, Header(alias=TOKEN_HEADER)]
AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]


def extract_token(
    participant_token: str | None = None,
    authorization: str | None = None,
) -> str | None:
    """Pull the token from either header form, preferring the explicit one."""
    if participant_token:
        return participant_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[len("bearer "):].strip()
    return None


def resolve_company_id(
    runtime: SessionRuntime,
    token: str | None,
    requested_company_id: int | None = None,
) -> int:
    """Return the company_id this caller may act as.

    Args:
        runtime: The session being acted on.
        token: Participant token from the request headers, if any.
        requested_company_id: What the caller asked for. Used only when the
            session has issued no tokens.

    Raises:
        HTTPException: 401 if the session requires a token and none was given or
            it is unknown. 403 if the token is valid but the caller asked to act
            as a different company.
    """
    if runtime.participants.is_empty():
        # No tokens issued for this session: legacy/unscored behaviour.
        return requested_company_id if requested_company_id is not None else 0

    participant = runtime.participants.resolve(token)
    if participant is None:
        raise HTTPException(
            status_code=401,
            detail=(
                f"A valid participant token is required. Pass it as {TOKEN_HEADER} "
                f"or 'Authorization: Bearer <token>'. Tokens are returned when the "
                f"session starts and written to the session directory."
            ),
        )

    if (
        requested_company_id is not None
        and requested_company_id != participant.company_id
    ):
        # Attribution matters more than convenience here: silently rewriting the
        # company would let a mis-configured agent appear to act for itself while
        # actually acting elsewhere.
        raise HTTPException(
            status_code=403,
            detail=(
                f"Token is scoped to company {participant.company_id} but the "
                f"request targets company {requested_company_id}"
            ),
        )

    return participant.company_id


def apply_company_scope(
    runtime: SessionRuntime,
    params: dict[str, Any],
    token: str | None,
    envelope_company_id: int | None = None,
) -> int:
    """Force ``params['company_id']`` to the company the token owns.

    Returns the authoritative company_id. Note this OVERWRITES rather than
    defaults: a caller-supplied company_id previously won via setdefault, which
    let any client act as any company.
    """
    requested = params.get("company_id", envelope_company_id)
    company_id = resolve_company_id(runtime, token, requested)
    params["company_id"] = company_id
    return company_id
