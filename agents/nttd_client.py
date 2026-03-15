import asyncio
import logging
from collections import deque
from typing import Any

import requests
import websockets

from nttd.schemas.snapshot import StateSnapshot

logger = logging.getLogger(__name__)

_WS_RECONNECT_BASE = 2.0
_WS_RECONNECT_CAP = 30.0


class NttdClient:
    """Shared HTTP + WebSocket transport for nttd agents.

    HTTP calls use requests (sync, safe to call from executor).
    WebSocket listener runs as an asyncio task managed by start_ws() / stop().
    """

    def __init__(
        self,
        base_url: str,
        agent_id: str,
        company_id: int,
        snapshot_history_len: int = 5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.agent_id = agent_id
        self.company_id = company_id
        self._history: deque[StateSnapshot] = deque(maxlen=snapshot_history_len)
        self._snapshot_queue: asyncio.Queue[StateSnapshot] = asyncio.Queue(maxsize=1)
        self._ws_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self) -> None:
        """POST /agents/connect to register this agent with the server."""
        payload = {
            "agent_id": self.agent_id,
            "name": self.agent_id,
            "company_scope": [self.company_id],
        }
        resp = requests.post(f"{self.base_url}/agents/connect", json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Registered agent %s (company %d)", self.agent_id, self.company_id)

    def unregister(self) -> None:
        """POST /agents/{id}/disconnect."""
        try:
            requests.post(f"{self.base_url}/agents/{self.agent_id}/disconnect", timeout=5)
        except Exception:
            logger.warning("Failed to unregister agent %s", self.agent_id)

    # ------------------------------------------------------------------
    # WebSocket
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
                async with websockets.connect(f"{ws_url}/ws/{self.agent_id}") as ws:
                    backoff = _WS_RECONNECT_BASE
                    logger.info("WebSocket connected for agent %s", self.agent_id)
                    async for raw in ws:
                        import json
                        msg = json.loads(raw)
                        if msg.get("type") == "snapshot":
                            snap = StateSnapshot.model_validate(msg["data"])
                            self._history.append(snap)
                            # Drop old unread snapshot and enqueue newest
                            try:
                                self._snapshot_queue.put_nowait(snap)
                            except asyncio.QueueFull:
                                try:
                                    self._snapshot_queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    pass
                                self._snapshot_queue.put_nowait(snap)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning(
                    "WebSocket disconnected for %s, reconnecting in %.0fs",
                    self.agent_id, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _WS_RECONNECT_CAP)
                self.register()

    # ------------------------------------------------------------------
    # Snapshot access
    # ------------------------------------------------------------------

    async def wait_for_snapshot(self) -> StateSnapshot:
        """Block until the next heartbeat snapshot arrives."""
        return await self._snapshot_queue.get()

    def get_snapshot_history(self, n: int = 5) -> list[StateSnapshot]:
        snaps = list(self._history)
        return list(reversed(snaps[-n:]))

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def get_compact_snapshot(self) -> dict[str, Any]:
        """GET /state/compact?company_id=N."""
        resp = requests.get(
            f"{self.base_url}/state/compact",
            params={"company_id": self.company_id},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def submit_heartbeat_action(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST /session/heartbeat/action."""
        payload = {
            "agent_id": self.agent_id,
            "action": action,
            "params": params or {},
        }
        resp = requests.post(f"{self.base_url}/session/heartbeat/action", json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def gs_query(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST /state/gs/query."""
        resp = requests.post(
            f"{self.base_url}/state/gs/query",
            params={"action": action},
            json=params or {},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
