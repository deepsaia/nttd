"""Authorization matrix for participant-scoped actions.

The property under test: the company an action affects is decided by the presented
token, never by a company_id the caller supplied. Before this, action_routes used
``params.setdefault("company_id", ...)``, so a caller-supplied value won and any
client could act as any company -- selling a rival's vehicles or claiming a
rival's score.

These tests exercise resolve_company_id/apply_company_scope directly rather than
through HTTP, because the HTTP path needs a running OpenTTD session.

Run with: uv run pytest tests/test_participant_authz.py -v
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from nttd.api.participant_auth import (
    apply_company_scope,
    extract_token,
    resolve_company_id,
)
from nttd.runtime.participant_registry import ParticipantRegistry


class _FakeRuntime:
    """Minimal stand-in exposing only what participant_auth reads."""

    def __init__(self) -> None:
        self.participants = ParticipantRegistry()


@pytest.fixture
def runtime() -> Any:
    return _FakeRuntime()


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------


def test_explicit_header_is_used() -> None:
    assert extract_token("pt_abc", None) == "pt_abc"


def test_bearer_authorization_is_accepted() -> None:
    assert extract_token(None, "Bearer pt_xyz") == "pt_xyz"
    assert extract_token(None, "bearer pt_xyz") == "pt_xyz", "scheme is case-insensitive"


def test_explicit_header_wins_over_authorization() -> None:
    assert extract_token("pt_explicit", "Bearer pt_other") == "pt_explicit"


def test_non_bearer_authorization_is_ignored() -> None:
    assert extract_token(None, "Basic dXNlcjpwYXNz") is None


def test_no_headers_yields_no_token() -> None:
    assert extract_token(None, None) is None


# ---------------------------------------------------------------------------
# The core matrix
# ---------------------------------------------------------------------------


def test_token_determines_the_company(runtime: Any) -> None:
    participant = runtime.participants.issue(company_id=1)
    assert resolve_company_id(runtime, participant.token, requested_company_id=1) == 1


def test_missing_token_is_rejected_when_tokens_exist(runtime: Any) -> None:
    runtime.participants.issue(company_id=0)
    with pytest.raises(HTTPException) as exc:
        resolve_company_id(runtime, None, requested_company_id=0)
    assert exc.value.status_code == 401


def test_unknown_token_is_rejected(runtime: Any) -> None:
    runtime.participants.issue(company_id=0)
    with pytest.raises(HTTPException) as exc:
        resolve_company_id(runtime, "pt_forged", requested_company_id=0)
    assert exc.value.status_code == 401


def test_acting_as_another_company_is_forbidden(runtime: Any) -> None:
    """The attack this whole mechanism exists to stop."""
    runtime.participants.issue(company_id=0)
    attacker = runtime.participants.issue(company_id=1)

    with pytest.raises(HTTPException) as exc:
        resolve_company_id(runtime, attacker.token, requested_company_id=0)
    assert exc.value.status_code == 403
    assert "scoped to company 1" in exc.value.detail


def test_omitted_company_id_defaults_to_the_token_company(runtime: Any) -> None:
    """An agent need not state its company; the token already says which."""
    participant = runtime.participants.issue(company_id=2)
    assert resolve_company_id(runtime, participant.token, requested_company_id=None) == 2


def test_revoked_token_stops_working(runtime: Any) -> None:
    stale = runtime.participants.issue(company_id=0)
    runtime.participants.issue(company_id=0)  # re-issue revokes the first

    with pytest.raises(HTTPException) as exc:
        resolve_company_id(runtime, stale.token, requested_company_id=0)
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# apply_company_scope OVERWRITES, it does not default
# ---------------------------------------------------------------------------


def test_supplied_company_id_is_overwritten_not_defaulted(runtime: Any) -> None:
    """Regression guard for the setdefault bug.

    With setdefault, params kept the caller's value and the token was ignored.
    """
    participant = runtime.participants.issue(company_id=3)
    params: dict[str, Any] = {"company_id": 3, "x": 10, "y": 20}

    assert apply_company_scope(runtime, params, participant.token) == 3
    assert params["company_id"] == 3
    assert params["x"] == 10, "other params are untouched"


def test_mismatched_company_id_in_params_is_forbidden(runtime: Any) -> None:
    runtime.participants.issue(company_id=0)
    attacker = runtime.participants.issue(company_id=1)
    params: dict[str, Any] = {"company_id": 0}

    with pytest.raises(HTTPException) as exc:
        apply_company_scope(runtime, params, attacker.token)
    assert exc.value.status_code == 403


def test_scope_injects_company_id_when_absent(runtime: Any) -> None:
    participant = runtime.participants.issue(company_id=4)
    params: dict[str, Any] = {"amount": 100_000}

    assert apply_company_scope(runtime, params, participant.token) == 4
    assert params["company_id"] == 4


def test_envelope_company_id_does_not_override_token(runtime: Any) -> None:
    """The envelope is caller-supplied too, so it gets no more trust than params."""
    runtime.participants.issue(company_id=0)
    attacker = runtime.participants.issue(company_id=1)

    with pytest.raises(HTTPException) as exc:
        apply_company_scope(runtime, {}, attacker.token, envelope_company_id=0)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Untokenised sessions stay usable
# ---------------------------------------------------------------------------


def test_untokenised_session_accepts_the_requested_company(runtime: Any) -> None:
    """Existing scenarios, examples, and the admin console predate tokens.

    A session that issued none is unscored, so the permissive path is safe there.
    """
    assert runtime.participants.is_empty()
    assert resolve_company_id(runtime, None, requested_company_id=2) == 2


def test_untokenised_session_defaults_to_company_zero(runtime: Any) -> None:
    assert resolve_company_id(runtime, None, requested_company_id=None) == 0


def test_untokenised_session_ignores_a_stray_token(runtime: Any) -> None:
    """A leftover token must not lock out a session that issued none."""
    assert resolve_company_id(runtime, "pt_leftover", requested_company_id=1) == 1
