"""Tests for the scored-session lock.

The lock is the only real protection a self-hosted benchmark has: it is session
state, not a credential, so there is nothing for a contestant to hold wrongly. It
stops the failure that actually happens, which is an agent or operator reaching a
deity power and silently invalidating an otherwise legitimate run.

Run with: uv run pytest tests/test_scored_lock.py -v
"""

from __future__ import annotations

from nttd.runtime.scored_lock import ScoredLock


def test_unscored_session_permits_everything() -> None:
    """Scenario authoring and debugging need the full surface."""
    lock = ScoredLock(scored=False)
    assert lock.check("deity/change_balance") is True
    assert lock.check("rcon") is True
    assert lock.blocked == []


def test_scored_session_refuses_and_records() -> None:
    lock = ScoredLock(scored=True)
    assert lock.check("deity/change_balance", game_date=715_900) is False

    assert len(lock.blocked) == 1
    attempt = lock.blocked[0]
    assert attempt.operation == "deity/change_balance"
    assert attempt.game_date == 715_900
    assert attempt.attempted_at is not None


def test_refusal_does_not_void_the_run() -> None:
    """Nothing happened, so the score stands. The attempt is merely visible.

    Voiding on a stray probe would destroy an otherwise legitimate long run.
    """
    lock = ScoredLock(scored=True)
    lock.check("deity/found_town")

    assert lock.clean_run is False, "the attempt is recorded"
    assert lock.summary()["blocked_attempts"] == 1


def test_clean_run_when_nothing_was_attempted() -> None:
    lock = ScoredLock(scored=True)
    assert lock.clean_run is True
    assert lock.summary() == {
        "scored": True,
        "clean_run": True,
        "blocked_attempts": 0,
        "blocked_operations": [],
    }


def test_every_attempt_is_recorded_in_order() -> None:
    """Refusals accumulate, so an audit sees the whole sequence."""
    lock = ScoredLock(scored=True)
    for op in ("rcon", "deity/set_max_loan", "rcon"):
        lock.check(op)

    assert [a.operation for a in lock.blocked] == ["rcon", "deity/set_max_loan", "rcon"]
    assert lock.summary()["blocked_attempts"] == 3
    assert lock.summary()["blocked_operations"] == ["deity/set_max_loan", "rcon"]


def test_detail_is_retained_for_the_audit_trail() -> None:
    lock = ScoredLock(scored=True)
    lock.check("gs/execute", detail="action=change_bank_balance")

    assert lock.blocked[0].detail == "action=change_bank_balance"


def test_summary_is_json_serialisable() -> None:
    """It goes into the result record, so it must survive serialisation."""
    import json

    lock = ScoredLock(scored=True)
    lock.check("rcon")
    assert json.loads(json.dumps(lock.summary()))["blocked_attempts"] == 1


def test_default_is_unscored() -> None:
    """Opt-in: an ordinary local session must not be locked down by surprise."""
    assert ScoredLock().scored is False
