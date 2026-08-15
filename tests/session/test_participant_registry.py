"""Tests for participant tokens.

The property being protected: an action is attributed to a company by its token,
never by a company_id the caller supplied. Without this, any client can act as
any company, so no score is attributable to a contestant.

Run with: uv run pytest tests/test_participant_registry.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

from nttd.runtime.participant_registry import ParticipantRegistry, new_token


def test_issued_token_resolves_to_its_company() -> None:
    registry = ParticipantRegistry()
    participant = registry.issue(company_id=0)

    resolved = registry.resolve(participant.token)
    assert resolved is not None
    assert resolved.company_id == 0


def test_tokens_are_unique_per_company() -> None:
    registry = ParticipantRegistry()
    a = registry.issue(company_id=0)
    b = registry.issue(company_id=1)

    assert a.token != b.token
    assert registry.resolve(a.token).company_id == 0  # type: ignore[union-attr]
    assert registry.resolve(b.token).company_id == 1  # type: ignore[union-attr]


def test_unknown_token_resolves_to_none() -> None:
    """The core check: an unrecognised bearer gets no company, so no action."""
    registry = ParticipantRegistry()
    registry.issue(company_id=0)

    assert registry.resolve("pt_deadbeef") is None
    assert registry.resolve(None) is None
    assert registry.resolve("") is None


def test_one_company_token_cannot_resolve_to_another() -> None:
    """Guards the rival-sabotage case that motivated tokens."""
    registry = ParticipantRegistry()
    victim = registry.issue(company_id=0)
    attacker = registry.issue(company_id=1)

    assert registry.resolve(attacker.token).company_id != victim.company_id  # type: ignore[union-attr]


def test_reissue_revokes_the_previous_token() -> None:
    registry = ParticipantRegistry()
    first = registry.issue(company_id=0)
    second = registry.issue(company_id=0)

    assert registry.resolve(first.token) is None, "old token must stop working"
    assert registry.resolve(second.token) is not None
    assert len(registry.participants()) == 1


def test_token_shape_is_prefixed_uuid() -> None:
    """Prefixed so it is identifiable in logs; uuid4 hex for entropy."""
    token = new_token()
    assert token.startswith("pt_")
    assert len(token) == len("pt_") + 32
    assert int(token.removeprefix("pt_"), 16) >= 0, "hex body"


def test_redacted_form_does_not_leak_the_token() -> None:
    registry = ParticipantRegistry()
    participant = registry.issue(company_id=0)

    redacted = participant.redacted()
    assert redacted != participant.token
    assert participant.token not in redacted
    assert redacted.startswith("pt_")


def test_participants_are_ordered_by_company() -> None:
    registry = ParticipantRegistry()
    registry.issue(company_id=2)
    registry.issue(company_id=0)
    registry.issue(company_id=1)

    assert [p.company_id for p in registry.participants()] == [0, 1, 2]


def test_empty_registry_reports_empty() -> None:
    registry = ParticipantRegistry()
    assert registry.is_empty() is True
    registry.issue(company_id=0)
    assert registry.is_empty() is False


# ---------------------------------------------------------------------------
# Persistence, so a separately launched agent process can read its token
# ---------------------------------------------------------------------------


def test_write_then_load_round_trips(tmp_path: Path) -> None:
    original = ParticipantRegistry()
    a = original.issue(company_id=0)
    b = original.issue(company_id=1)
    original.write(tmp_path)

    restored = ParticipantRegistry()
    assert restored.load(tmp_path) == 2
    assert restored.resolve(a.token).company_id == 0  # type: ignore[union-attr]
    assert restored.resolve(b.token).company_id == 1  # type: ignore[union-attr]


def test_written_file_is_owner_only(tmp_path: Path) -> None:
    """Tokens are secrets, so the file must not be world-readable."""
    registry = ParticipantRegistry()
    registry.issue(company_id=0)
    path = registry.write(tmp_path)

    assert path.stat().st_mode & 0o077 == 0


def test_written_file_maps_company_to_token(tmp_path: Path) -> None:
    registry = ParticipantRegistry()
    participant = registry.issue(company_id=3)
    path = registry.write(tmp_path)

    assert json.loads(path.read_text()) == {"3": participant.token}


def test_load_of_missing_file_is_zero(tmp_path: Path) -> None:
    assert ParticipantRegistry().load(tmp_path) == 0


def test_load_of_corrupt_file_is_zero(tmp_path: Path) -> None:
    """A damaged file must not crash session recovery."""
    (tmp_path / "participants.json").write_text("{not json")
    assert ParticipantRegistry().load(tmp_path) == 0


def test_remove_deletes_the_token_file(tmp_path: Path) -> None:
    registry = ParticipantRegistry()
    registry.issue(company_id=0)
    registry.write(tmp_path)

    ParticipantRegistry.remove(tmp_path)
    assert not (tmp_path / "participants.json").exists()

    # Idempotent, since stop may run more than once.
    ParticipantRegistry.remove(tmp_path)
