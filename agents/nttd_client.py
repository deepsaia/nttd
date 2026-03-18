import asyncio
import logging
from collections import deque
from typing import Any

import requests
import websockets

logger = logging.getLogger(__name__)

_WS_RECONNECT_BASE = 2.0
_WS_RECONNECT_CAP = 30.0


class NttdClient:
    """Shared HTTP + WebSocket transport for nttd agents.

    HTTP calls use requests (sync, safe to call from executor).
    WebSocket listener runs as an asyncio task managed by start_ws() / stop().

    WebSocket delivers lightweight "heartbeat" trigger messages; actual game
    state is fetched via HTTP tool calls (see agents/tools.py).
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
        # Rolling history of compact snapshots (dicts) for trend data
        self._history: deque[dict[str, Any]] = deque(maxlen=snapshot_history_len)
        # Queue: agent's run() loop blocks here waiting for each heartbeat beat
        self._snapshot_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
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
        import json as _json

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        backoff = _WS_RECONNECT_BASE
        while True:
            try:
                async with websockets.connect(
                    f"{ws_url}/ws/{self.agent_id}",
                    ping_interval=None,   # server sends keepalive pings; disable client auto-ping
                ) as ws:
                    backoff = _WS_RECONNECT_BASE
                    logger.info("WebSocket connected for agent %s", self.agent_id)
                    async for raw in ws:
                        msg = _json.loads(raw)
                        msg_type = msg.get("type")

                        if msg_type == "heartbeat":
                            # Lightweight trigger from server — no full state serialization
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
                            # Application-level keepalive from server — ignore
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
        """Block until the next heartbeat trigger arrives.

        Returns a lightweight trigger dict:
          {type, game_date, paused, mode, companies, towns, vehicles}

        Use HTTP tool calls (NttdTools) to fetch full game state.
        """
        return await self._snapshot_queue.get()

    def get_snapshot_history(self, n: int = 5) -> list[dict[str, Any]]:
        """Last N heartbeat trigger dicts, newest first."""
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
