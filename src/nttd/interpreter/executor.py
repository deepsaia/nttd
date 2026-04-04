"""Executor — submits parsed agent actions to the nttd REST API.

Takes a list of AgentAction objects, wraps them in ActionEnvelopes,
and submits them to the session's action endpoint.
"""

import logging
import uuid
from typing import Any

import httpx

from nttd.interpreter.action_schema import AgentAction

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Submits agent actions to nttd REST API as ActionEnvelopes."""

    def __init__(self, base_url: str, session_id: str, company_id: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.company_id = company_id
        self._session_url = f"{self.base_url}/sessions/{self.session_id}"

    def _to_envelope(self, action: AgentAction) -> dict[str, Any]:
        """Convert an AgentAction to an ActionEnvelope dict."""
        return {
            "action_id": f"interp_{uuid.uuid4().hex[:8]}",
            "company_id": self.company_id,
            "action_type": action.action_type,
            "parameters": {**action.parameters, "company_id": self.company_id},
            "mode": "atomic",
        }

    async def execute(self, actions: list[AgentAction]) -> list[dict[str, Any]]:
        """Submit actions to nttd and return results.

        Uses the batch endpoint when multiple actions are provided
        for sequential execution under a single company lock acquisition.
        """
        if not actions:
            return []

        envelopes = [self._to_envelope(a) for a in actions]

        async with httpx.AsyncClient(timeout=30.0) as client:
            if len(envelopes) == 1:
                resp = await client.post(
                    f"{self._session_url}/actions/submit",
                    json=envelopes[0],
                )
                resp.raise_for_status()
                return [resp.json()]

            resp = await client.post(
                f"{self._session_url}/actions/submit-batch",
                json=envelopes,
            )
            resp.raise_for_status()
            return resp.json()

    async def execute_single(self, action: AgentAction) -> dict[str, Any]:
        """Submit a single action and return the result."""
        results = await self.execute([action])
        return results[0] if results else {}
