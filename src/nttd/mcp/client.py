"""Async HTTP client for calling the nttd REST API from the MCP server.

Each MCP server instance is configured with a specific session, agent, and company.
All requests are session-scoped.
"""

import logging
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class NttdMCPClient:
    """Async HTTP client wrapping the nttd REST API for MCP tool implementations."""

    def __init__(
        self,
        base_url: str,
        session_id: str,
        agent_id: str,
        company_id: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.agent_id = agent_id
        self.company_id = company_id
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        self._registered = False

    @property
    def _session_url(self) -> str:
        return f"/sessions/{self.session_id}"

    async def _ensure_registered(self) -> None:
        """Auto-register agent on first API call."""
        if self._registered:
            return
        resp = await self._http.post(
            f"{self._session_url}/agents/connect",
            json={
                "agent_id": self.agent_id,
                "name": self.agent_id,
                "company_scope": [self.company_id],
            },
        )
        resp.raise_for_status()
        self._registered = True
        logger.info("MCP agent registered: %s (session=%s, co=%d)", self.agent_id, self.session_id, self.company_id)

    async def observe_compact(self, company_id: int | None = None) -> dict[str, Any]:
        """GET /sessions/{sid}/state/compact."""
        await self._ensure_registered()
        cid = company_id if company_id is not None else self.company_id
        resp = await self._http.get(f"{self._session_url}/state/compact", params={"company_id": cid})
        resp.raise_for_status()
        return resp.json()

    async def observe_full(self) -> dict[str, Any]:
        """GET /sessions/{sid}/state/full."""
        await self._ensure_registered()
        resp = await self._http.get(f"{self._session_url}/state/full")
        resp.raise_for_status()
        return resp.json()

    async def submit_action(self, action_type: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST /sessions/{sid}/actions/submit with ActionEnvelope."""
        await self._ensure_registered()
        envelope = {
            "action_id": f"mcp_{uuid.uuid4().hex[:8]}",
            "company_id": self.company_id,
            "action_type": action_type,
            "parameters": params or {},
            "mode": "atomic",
        }
        resp = await self._http.post(f"{self._session_url}/actions/submit", json=envelope)
        resp.raise_for_status()
        return resp.json()

    async def gs_query(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST /sessions/{sid}/state/gs/query: live GS round-trip."""
        await self._ensure_registered()
        resp = await self._http.post(
            f"{self._session_url}/state/gs/query",
            params={"action": action},
            json=params or {},
        )
        resp.raise_for_status()
        return resp.json()

    async def pathfind(
        self,
        from_x: int, from_y: int,
        to_x: int, to_y: int,
        transport_type: str = "road",
        avoid_demolish: bool = False,
    ) -> dict[str, Any]:
        """POST /admin/sessions/{sid}/pathfind."""
        await self._ensure_registered()
        resp = await self._http.post(
            f"/admin/sessions/{self.session_id}/pathfind",
            json={
                "from_x": from_x, "from_y": from_y,
                "to_x": to_x, "to_y": to_y,
                "transport_type": transport_type,
                "company_id": self.company_id,
                "avoid_demolish": avoid_demolish,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def get_session_status(self) -> dict[str, Any]:
        """GET /sessions/{sid}/status."""
        resp = await self._http.get(f"{self._session_url}/status")
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()
