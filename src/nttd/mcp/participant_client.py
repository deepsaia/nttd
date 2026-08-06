"""HTTP client for the participant tier, used by the MCP tools.

Replaces a client written before participant tokens existed. That one called the legacy
unprefixed paths, registered itself through ``/agents/connect``, and put ``company_id``
in every action envelope. None of that is how a contestant plays now: the tiered routes
take a token, and the participant routes overwrite the company in the body with the one
the token identifies. Sending it was at best ignored and at worst misleading, since it
read as though the caller chose.

One session, one token, one company. A server instance is a seat at a game rather than a
console for the whole thing, which is what makes the tool surface small enough to be
worth having: no tool needs a session argument, so no client can address the wrong one.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from nttd.api.participant_auth import TOKEN_HEADER

logger = logging.getLogger(__name__)

# Pathfinding builds run inside the game and a long one outlasts a default timeout, which
# presents as a dead server rather than a slow move.
_TIMEOUT_SECONDS = 180.0


class ParticipantClient:
    """Calls the participant tier of one nttd session, as one company."""

    def __init__(self, base_url: str, session_id: str, participant_token: str) -> None:
        self._session_id = session_id
        self._base = f"/v1/participant/sessions/{session_id}"
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=_TIMEOUT_SECONDS,
            headers={TOKEN_HEADER: participant_token},
        )

    @property
    def session_id(self) -> str:
        return self._session_id

    async def observe(self) -> dict[str, Any]:
        """The whole world state.

        Deliberately not a filtered view. nttd hands over everything and leaves the
        choosing to the agent, because deciding what matters is the task rather than
        something the environment should have done first.
        """
        response = await self._http.get(f"{self._base}/state/full")
        response.raise_for_status()
        return response.json()

    async def submit(self, action_type: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Submit one action. The company comes from the token, never from here."""
        envelope = {
            "action_id": f"mcp_{uuid.uuid4().hex[:8]}",
            "action_type": action_type,
            "parameters": parameters,
            "mode": "atomic",
        }
        response = await self._http.post(f"{self._base}/actions/submit", json=envelope)
        response.raise_for_status()
        return response.json()

    async def validate(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Check a list of actions without running any of them."""
        response = await self._http.post(
            f"{self._base}/actions/interpret/validate", json={"actions": actions},
        )
        response.raise_for_status()
        return response.json()

    async def query(self, action_type: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Run a read-only GameScript query and return its reply."""
        response = await self._http.post(
            f"{self._base}/state/gs/query", params={"action": action_type}, json=parameters,
        )
        response.raise_for_status()
        return response.json()

    async def step(
        self, actions: list[dict[str, Any]], days: int | None = None,
    ) -> dict[str, Any]:
        """Flush a batch of actions, advance the world, and observe, in one call.

        Actions and the advance are one request because that is what the barrier is:
        the reply is the world after the moves landed, so a policy never has to guess
        when they took effect. Submitting separately and then stepping would reintroduce
        exactly that guess.
        """
        body: dict[str, Any] = {"actions": actions}
        if days is not None:
            body["days"] = days
        response = await self._http.post(f"{self._base}/step", json=body)
        response.raise_for_status()
        return response.json()

    async def status(self) -> dict[str, Any]:
        """Session status, which is public tier: it belongs to nobody in particular."""
        response = await self._http.get(
            f"/v1/public/sessions/{self._session_id}/status",
        )
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        await self._http.aclose()
