"""Shared HTTP + WebSocket transport for nttd agents.

HTTP calls use requests (sync, safe to call from executor).
WebSocket listener runs as an asyncio task managed by start_ws() / stop().

All URLs are session-scoped: ``/sessions/{session_id}/...``.
"""

import asyncio
import json as _json
import logging
import uuid
from collections import deque
from typing import Any

import requests
import websockets

logger = logging.getLogger(__name__)

_WS_RECONNECT_BASE = 2.0
_WS_RECONNECT_CAP = 30.0


class NttdClient:
    """HTTP + WebSocket transport for nttd agents.

    Supports two modes:
    - **Heartbeat** (legacy): WebSocket delivers triggers; agent uses ``wait_for_snapshot()``.
    - **Real-time**: Agent calls ``get_compact_snapshot()`` / ``submit_action()`` in a loop.

    All URLs include ``/sessions/{session_id}/`` for multi-session support.
    """

    def __init__(
        self,
        base_url: str,
        session_id: str,
        agent_id: str,
        company_id: int,
        snapshot_history_len: int = 5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.agent_id = agent_id
        self.company_id = company_id
        # Rolling history of compact snapshots (dicts) for trend data
        self._history: deque[dict[str, Any]] = deque(maxlen=snapshot_history_len)
        # Queue: agent's run() loop blocks here waiting for each heartbeat beat
        self._snapshot_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        self._ws_task: asyncio.Task[None] | None = None

    @property
    def _session_url(self) -> str:
        """Base URL for session-scoped endpoints."""
        return f"{self.base_url}/sessions/{self.session_id}"

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self) -> None:
        """POST /sessions/{sid}/agents/connect to register this agent."""
        payload = {
            "agent_id": self.agent_id,
            "name": self.agent_id,
            "company_scope": [self.company_id],
        }
        resp = requests.post(f"{self._session_url}/agents/connect", json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Registered agent %s (session=%s, company=%d)", self.agent_id, self.session_id, self.company_id)

    def unregister(self) -> None:
        """POST /sessions/{sid}/agents/{id}/disconnect."""
        try:
            requests.post(f"{self._session_url}/agents/{self.agent_id}/disconnect", timeout=5)
        except Exception:
            logger.warning("Failed to unregister agent %s", self.agent_id)

    # ------------------------------------------------------------------
    # WebSocket (heartbeat mode)
    # ------------------------------------------------------------------

    async def start_ws(self) -> None:
        """Start the WebSocket listener task (auto-reconnects with backoff)."""
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def stop(self) -> None:
        """Cancel WebSocket task and unregister."""
        if self._ws_task is not None:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        self.unregister()

    async def _ws_loop(self) -> None:
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        backoff = _WS_RECONNECT_BASE
        while True:
            try:
                async with websockets.connect(
                    f"{ws_url}/ws/{self.session_id}/{self.agent_id}",
                    ping_interval=None,
                ) as ws:
                    backoff = _WS_RECONNECT_BASE
                    logger.info("WebSocket connected for agent %s", self.agent_id)
                    async for raw in ws:
                        msg = _json.loads(raw)
                        msg_type = msg.get("type")

                        if msg_type == "heartbeat":
                            self._history.append(msg)
                            try:
                                self._snapshot_queue.put_nowait(msg)
                            except asyncio.QueueFull:
                                try:
                                    self._snapshot_queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    pass
                                self._snapshot_queue.put_nowait(msg)

                        elif msg_type == "ping":
                            pass

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(
                    "WebSocket error for %s, reconnecting in %.0fs: %s",
                    self.agent_id, backoff, exc,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _WS_RECONNECT_CAP)
                self.register()

    # ------------------------------------------------------------------
    # Snapshot access
    # ------------------------------------------------------------------

    async def wait_for_snapshot(self) -> dict[str, Any]:
        """Block until the next heartbeat trigger arrives (heartbeat mode)."""
        return await self._snapshot_queue.get()

    def get_snapshot_history(self, n: int = 5) -> list[dict[str, Any]]:
        """Last N heartbeat trigger dicts, newest first."""
        snaps = list(self._history)
        return list(reversed(snaps[-n:]))

    # ------------------------------------------------------------------
    # HTTP helpers — session-scoped
    # ------------------------------------------------------------------

    def get_compact_snapshot(self) -> dict[str, Any]:
        """GET /sessions/{sid}/state/compact?company_id=N."""
        resp = requests.get(
            f"{self._session_url}/state/compact",
            params={"company_id": self.company_id},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def submit_action(self, action_type: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST /sessions/{sid}/actions/submit with a proper ActionEnvelope."""
        envelope = {
            "action_id": f"act_{uuid.uuid4().hex[:8]}",
            "company_id": self.company_id,
            "action_type": action_type,
            "parameters": params or {},
            "mode": "atomic",
        }
        resp = requests.post(f"{self._session_url}/actions/submit", json=envelope, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def submit_actions_batch(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """POST /sessions/{sid}/actions/submit-batch with a list of ActionEnvelopes.

        Each dict in ``actions`` should have ``action_type`` and optionally ``params``.
        Returns a list of ActionResult dicts in the same order.
        """
        envelopes = []
        for action in actions:
            envelopes.append({
                "action_id": f"act_{uuid.uuid4().hex[:8]}",
                "company_id": self.company_id,
                "action_type": action["action_type"],
                "parameters": action.get("params", {}),
                "mode": "atomic",
            })
        resp = requests.post(f"{self._session_url}/actions/submit-batch", json=envelopes, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def submit_heartbeat_action(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST /sessions/{sid}/session/heartbeat/action (heartbeat mode only)."""
        payload = {
            "agent_id": self.agent_id,
            "action": action,
            "params": params or {},
        }
        resp = requests.post(f"{self._session_url}/session/heartbeat/action", json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def gs_query(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST /sessions/{sid}/state/gs/query."""
        resp = requests.post(
            f"{self._session_url}/state/gs/query",
            params={"action": action},
            json=params or {},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
