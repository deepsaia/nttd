"""Participant tokens: which contestant may act as which company.

Each company that a contestant controls gets an opaque bearer token when the
session starts. Every action is attributed to a company by looking up its token,
never by trusting a company_id the caller supplied -- otherwise any client could
sell a rival's vehicles or claim a rival's score.

Scope of the protection: nttd is self-hosted, so a contestant already controls
the process and could bypass any in-process check. These tokens are not a defence
against the host. They stop an *agent* from acting outside its company, which is
the failure that actually happens: an LLM handed a tool list will try things, and
without attribution a run's score cannot be tied to a contestant at all.

Tokens are uuid4 (122 bits of entropy, no custom crypto) and compared in constant
time, so the same code is sound if an instance is ever exposed.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_TOKEN_PREFIX = "pt_"
_TOKEN_FILENAME = "participants.json"


@dataclass(frozen=True)
class Participant:
    """A contestant's claim on one company."""

    company_id: int
    token: str

    def redacted(self) -> str:
        """Token form safe to log: enough to correlate, not enough to reuse."""
        return f"{self.token[:len(_TOKEN_PREFIX) + 6]}..."


def new_token() -> str:
    return f"{_TOKEN_PREFIX}{uuid.uuid4().hex}"


class ParticipantRegistry:
    """Maps participant tokens to the company they may act as.

    One registry per session, owned by SessionRuntime.
    """

    def __init__(self) -> None:
        self._by_token: dict[str, Participant] = {}

    def issue(self, company_id: int) -> Participant:
        """Mint a token for a company. Re-issuing replaces the previous one."""
        existing = self.for_company(company_id)
        if existing is not None:
            self._by_token.pop(existing.token, None)

        participant = Participant(company_id=company_id, token=new_token())
        self._by_token[participant.token] = participant
        logger.info(
            "Issued participant token %s for company %d",
            participant.redacted(), company_id,
        )
        return participant

    def resolve(self, token: str | None) -> Participant | None:
        """Return the participant for a token, or None if it is unknown.

        Uses a constant-time comparison so a caller cannot learn a valid token
        byte by byte from response timing.
        """
        if not token:
            return None
        for candidate, participant in self._by_token.items():
            if secrets.compare_digest(candidate, token):
                return participant
        return None

    def for_company(self, company_id: int) -> Participant | None:
        return next(
            (p for p in self._by_token.values() if p.company_id == company_id), None
        )

    def participants(self) -> list[Participant]:
        return sorted(self._by_token.values(), key=lambda p: p.company_id)

    def is_empty(self) -> bool:
        return not self._by_token

    # -- Persistence ------------------------------------------------------
    #
    # A contestant's agent or MAS often runs as a separate process that did not
    # see the start response, so the tokens are also written to the session
    # directory. They are secrets: never recorded in parquet, and removed when
    # the session stops.

    def write(self, session_dir: Path) -> Path:
        """Write tokens to the session directory for other local processes."""
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / _TOKEN_FILENAME
        payload = {str(p.company_id): p.token for p in self.participants()}
        path.write_text(json.dumps(payload, indent=2))
        path.chmod(0o600)
        logger.info("Wrote %d participant token(s) to %s", len(payload), path)
        return path

    def load(self, session_dir: Path) -> int:
        """Restore tokens from the session directory. Returns the count loaded.

        Used on orphan recovery so a reconnected session keeps honouring the
        tokens its agents already hold.
        """
        path = Path(session_dir) / _TOKEN_FILENAME
        if not path.exists():
            return 0
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            logger.exception("Could not read participant tokens at %s", path)
            return 0

        self._by_token.clear()
        for company_id, token in payload.items():
            participant = Participant(company_id=int(company_id), token=str(token))
            self._by_token[participant.token] = participant
        return len(self._by_token)

    @staticmethod
    def remove(session_dir: Path) -> None:
        """Delete the token file. Called when a session stops."""
        path = Path(session_dir) / _TOKEN_FILENAME
        if path.exists():
            path.unlink()
