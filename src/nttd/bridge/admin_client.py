import asyncio
import json
import logging
from typing import Any, Callable

from pyopenttdadmin.enums import (
    AdminUpdateFrequency,
    AdminUpdateType,
    PacketType,
)
from pyopenttdadmin.packet import (
    AdminChatPacket,
    AdminJoinPacket,
    AdminRconPacket,
    AdminSubscribePacket,
    GameScriptPacket,
    Packet,
    ProtocolPacket,
    RconEndPacket,
    RconPacket,
    ShutdownPacket,
    WelcomePacket,
)

logger = logging.getLogger(__name__)

_RECONNECT_BASE_DELAY = 2.0   # seconds before first retry
_RECONNECT_MAX_DELAY  = 30.0  # cap on backoff


class AdminGameScriptPacket(Packet):
    """Packet to send JSON data to the in-game GameScript (ADMIN_GAMESCRIPT, type 6)."""

    packet_type = PacketType.ADMIN_GAMESCRIPT

    def __init__(self, json_str: str) -> None:
        self.json_str = json_str

    def to_bytes(self) -> bytes:
        return f"{self.json_str}\x00".encode("utf-8")


class AdminClient:
    """Async TCP client for the OpenTTD admin port with auto-reconnect."""

    def __init__(self, host: str = "127.0.0.1", port: int = 3977) -> None:
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._handlers: dict[PacketType, list[Any]] = {}
        self._rcon_buffer: list[str] = []
        self._rcon_event: asyncio.Event = asyncio.Event()
        self.welcome: WelcomePacket | None = None

        # Credentials stored for reconnect
        self._password: str = ""
        self._name: str = "nttd"

        # Callbacks fired after each successful (re)connect
        self._reconnect_callbacks: list[Callable[[], Any]] = []

        # GameScript response tracking
        self._gs_responses: dict[str, list[dict[str, Any]]] = {}
        self._gs_events: dict[str, asyncio.Event] = {}
        self._gs_totals: dict[str, int] = {}
        self._gs_counter: int = 0

        # Set to True to suppress reconnect after an intentional disconnect()
        self._intentional_disconnect = False

        # Callbacks for unsolicited GS game events (_event=true)
        self._event_callbacks: list[Callable[[dict[str, Any]], Any]] = []

    @property
    def connected(self) -> bool:
        return self._connected

    def on_reconnect(self, callback: Callable[[], Any]) -> None:
        """Register a callback to be called after every successful (re)connect."""
        self._reconnect_callbacks.append(callback)

    def on_game_event(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        """Register a callback for unsolicited GS game events."""
        self._event_callbacks.append(callback)

    async def health_ping(self) -> bool:
        """Ping the GS to verify the connection is alive."""
        if not self._connected:
            return False
        try:
            result = await self.send_gamescript("ping", timeout=5.0)
            return result.get("success", False)
        except Exception:
            return False

    async def connect(self, password: str, name: str = "nttd") -> bool:
        self._password = password
        self._name = name
        self._intentional_disconnect = False
        return await self._connect_once()

    async def _connect_once(self) -> bool:
        try:
            self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        except OSError as e:
            logger.error("Failed to connect to %s:%d: %s", self.host, self.port, e)
            return False

        join_packet = AdminJoinPacket(self._password, self._name, "1")
        await self._send(join_packet)

        protocol = await self._recv_one()
        if not isinstance(protocol, ProtocolPacket):
            logger.error("Expected ProtocolPacket, got %s", type(protocol).__name__)
            return False

        welcome = await self._recv_one()
        if not isinstance(welcome, WelcomePacket):
            logger.error("Expected WelcomePacket, got %s", type(welcome).__name__)
            return False

        logger.info(
            "Connected to %s (OpenTTD %s, map %dx%d)",
            welcome.server_name, welcome.version, welcome.mapwidth, welcome.mapheight,
        )
        self.welcome = welcome
        self._connected = True
        return True

    async def _reconnect_loop(self) -> None:
        """Exponential backoff reconnect loop, called after an unexpected disconnect."""
        delay = _RECONNECT_BASE_DELAY
        attempt = 0

        while not self._intentional_disconnect:
            attempt += 1
            logger.info("Reconnect attempt %d in %.0fs...", attempt, delay)
            await asyncio.sleep(delay)

            if await self._connect_once():
                logger.info("Reconnected to OpenTTD (attempt %d)", attempt)
                # Fire all registered post-reconnect callbacks
                for cb in self._reconnect_callbacks:
                    try:
                        result = cb()
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        logger.exception("Reconnect callback failed")
                return

            delay = min(delay * 2, _RECONNECT_MAX_DELAY)

    async def subscribe(self, update_type: AdminUpdateType, frequency: AdminUpdateFrequency) -> None:
        packet = AdminSubscribePacket(update_type, frequency)
        await self._send(packet)

    async def subscribe_defaults(self) -> None:
        await self.subscribe(AdminUpdateType.DATE, AdminUpdateFrequency.DAILY)
        await self.subscribe(AdminUpdateType.COMPANY_INFO, AdminUpdateFrequency.AUTOMATIC)
        await self.subscribe(AdminUpdateType.COMPANY_ECONOMY, AdminUpdateFrequency.QUARTERLY)
        await self.subscribe(AdminUpdateType.COMPANY_STATS, AdminUpdateFrequency.QUARTERLY)
        await self.subscribe(AdminUpdateType.CHAT, AdminUpdateFrequency.AUTOMATIC)
        await self.subscribe(AdminUpdateType.CONSOLE, AdminUpdateFrequency.AUTOMATIC)
        await self.subscribe(AdminUpdateType.GAMESCRIPT, AdminUpdateFrequency.AUTOMATIC)

    async def send_rcon(self, command: str) -> list[str]:
        self._rcon_buffer.clear()
        self._rcon_event.clear()
        packet = AdminRconPacket(command)
        await self._send(packet)
        try:
            await asyncio.wait_for(self._rcon_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Rcon command timed out: %s", command)
        return list(self._rcon_buffer)

    async def send_chat(self, message: str) -> None:
        packet = AdminChatPacket(message)
        await self._send(packet)

    async def send_gamescript(
        self, action: str, params: dict[str, Any] | None = None, timeout: float = 10.0
    ) -> dict[str, Any]:
        """Send a command to the GameScript and wait for the correlated response."""
        self._gs_counter += 1
        correlation_id = f"gs_{self._gs_counter}"

        msg: dict[str, Any] = {"id": correlation_id, "action": action}
        if params:
            msg["params"] = params

        self._gs_responses[correlation_id] = []
        self._gs_events[correlation_id] = asyncio.Event()
        self._gs_totals[correlation_id] = 1

        json_str = json.dumps(msg)
        packet = AdminGameScriptPacket(json_str)
        await self._send(packet)

        try:
            await asyncio.wait_for(self._gs_events[correlation_id].wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("GameScript command timed out: %s (id=%s)", action, correlation_id)
            return {"id": correlation_id, "success": False, "error": "timeout"}
        finally:
            self._gs_events.pop(correlation_id, None)
            self._gs_totals.pop(correlation_id, None)

        chunks = self._gs_responses.pop(correlation_id, [])
        if not chunks:
            return {"id": correlation_id, "success": False, "error": "empty"}

        if len(chunks) == 1:
            return chunks[0]

        chunks.sort(key=lambda c: c.get("_chunk", 0))
        merged_result: list[Any] = []
        for chunk in chunks:
            result = chunk.get("result", [])
            if isinstance(result, list):
                merged_result.extend(result)
            else:
                merged_result.append(result)

        return {"id": correlation_id, "success": chunks[0].get("success", True), "result": merged_result}

    def _handle_gs_response(self, data: dict[str, Any]) -> None:
        # Unsolicited game event from GS event listener
        if data.get("_event"):
            for cb in self._event_callbacks:
                try:
                    cb(data)
                except Exception:
                    logger.exception("GS event callback error")
            return

        cid = data.get("id", "")
        if cid not in self._gs_events:
            logger.debug("GS response for unknown id: %s", cid)
            return
        total = data.get("_total", 1)
        self._gs_totals[cid] = total
        self._gs_responses[cid].append(data)
        if len(self._gs_responses[cid]) >= total:
            self._gs_events[cid].set()

    def on(self, packet_type: PacketType, handler: Any) -> None:
        if packet_type not in self._handlers:
            self._handlers[packet_type] = []
        self._handlers[packet_type].append(handler)

    async def poll_loop(self) -> None:
        """Main receive loop. On unexpected disconnect, triggers reconnect."""
        while True:
            if not self._connected:
                break

            try:
                packet = await self._recv_one()
            except (ConnectionError, asyncio.IncompleteReadError, OSError):
                if self._intentional_disconnect:
                    break
                logger.error("Connection lost — will attempt reconnect")
                self._connected = False
                # Cancel pending GS requests
                for event in self._gs_events.values():
                    event.set()
                await self._reconnect_loop()
                if self._connected:
                    # Resume poll loop after successful reconnect
                    continue
                break

            if packet is None:
                continue

            if isinstance(packet, ShutdownPacket):
                logger.info("Server shutting down")
                self._connected = False
                if not self._intentional_disconnect:
                    await self._reconnect_loop()
                    if self._connected:
                        continue
                break

            if isinstance(packet, RconPacket):
                self._rcon_buffer.append(packet.response)
                continue

            if isinstance(packet, RconEndPacket):
                self._rcon_event.set()
                continue

            if isinstance(packet, GameScriptPacket):
                try:
                    raw = packet.json.rstrip("\x00")
                    data = json.loads(raw)
                    logger.debug("GS response: %s", data)
                    self._handle_gs_response(data)
                except (json.JSONDecodeError, AttributeError) as e:
                    logger.warning("Failed to parse GS packet: %s (raw=%r)", e, packet.json)
                continue

            await self._dispatch(packet)

    async def disconnect(self) -> None:
        self._intentional_disconnect = True
        self._connected = False
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None

    async def _send(self, packet: Packet) -> None:
        if self._writer is None:
            raise ConnectionError("Not connected")
        data = packet.to_bytes()
        packet_type_byte = packet.packet_type.value.to_bytes(1, "little")
        length = (len(data) + 3).to_bytes(2, "little")
        self._writer.write(length + packet_type_byte + data)
        await self._writer.drain()

    async def _recv_one(self) -> Packet | None:
        if self._reader is None:
            raise ConnectionError("Not connected")
        header = await self._reader.readexactly(2)
        packet_len = int.from_bytes(header, "little")
        body = await self._reader.readexactly(packet_len - 2)
        try:
            return Packet.create_packet(body)
        except (ValueError, KeyError) as e:
            logger.warning("Unknown packet type 0x%02x: %s", body[0], e)
            return None

    async def _dispatch(self, packet: Packet) -> None:
        handlers = self._handlers.get(packet.packet_type, [])
        for handler in handlers:
            try:
                result = handler(packet)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Handler error for %s", type(packet).__name__)
