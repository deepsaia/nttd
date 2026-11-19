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
from typing import Any

import httpx

from nttd.api.participant_auth import TOKEN_HEADER

logger = logging.getLogger(__name__)

# Pathfinding builds run inside the game and a long one outlasts a default timeout, which
# presents as a dead server rather than a slow move.
_TIMEOUT_SECONDS = 180.0
# A step and a submitted batch run until the game answers. The game bounds each
# command itself, 120 s for a connection and 10 s otherwise. A call given up on
# here would keep running in the game, refuse the next batch, and lose its results.
_RUN_TIMEOUT = httpx.Timeout(_TIMEOUT_SECONDS, read=None)


class ParticipantClient:
    """Calls the participant tier of one nttd session, as one company.

    The token is optional. A session that issued no tokens takes the company from
    the request body instead and ignores the header.
    """

    def __init__(self, base_url: str, session_id: str, participant_token: str | None = None) -> None:
        self._session_id = session_id
        self._base = f"/v1/participant/sessions/{session_id}"
        headers = {TOKEN_HEADER: participant_token} if participant_token else {}
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=_TIMEOUT_SECONDS,
            headers=headers,
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

    async def submit_batch(self, envelopes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Submit several actions in one request, for a game that keeps its own clock.

        Returns one result per envelope, in order, each carrying its action_id.
        """
        response = await self._http.post(
            f"{self._base}/actions/submit-batch", json=envelopes, timeout=_RUN_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    async def validate(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Check a list of actions without running any of them.

        The route takes the list itself as the body, not an object around it.
        """
        response = await self._http.post(
            f"{self._base}/actions/interpret/validate", json=actions,
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
        response = await self._http.post(f"{self._base}/step", json=body, timeout=_RUN_TIMEOUT)
        response.raise_for_status()
        return response.json()

    async def reset(self) -> dict[str, Any]:
        """Enter stepped mode and return the opening observation.

        The game refuses every step from a caller that has not done this once. It is
        idempotent: calling it again re-pauses and re-observes without restarting.
        """
        response = await self._http.post(f"{self._base}/step/reset", json={})
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
