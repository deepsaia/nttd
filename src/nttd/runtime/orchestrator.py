"""Runtime orchestrator: controls the heartbeat and async real-time loops.

Heartbeat mode is the primary mode for agent benchmarking:
  pause → GS refresh → snapshot → action window → execute actions → unpause → advance N days → repeat
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from nttd.actions.gate import admit
from nttd.actions.gs_reply import result_from_reply
from nttd.actions.tracker import ActionTracker
from nttd.bridge.admin_client import AdminClient
from nttd.config.scenario_config import EndConditionsConfig, ScenarioConfig
from nttd.constants import TICK_DEPENDENT_ACTIONS
from nttd.runtime.company_lock import CompanyLockManager
from nttd.runtime.end_conditions import EndConditionChecker
from nttd.schemas.action_envelope import ActionEnvelope, ActionMode
from nttd.schemas.action_result import ActionResult, ActionStatus
from nttd.schemas.game import RuntimeMode
from nttd.schemas.snapshot import StateSnapshot
from nttd.schemas.step_result import StepResult
from nttd.state.tile_footprint import affected_area
from nttd.state.world import WorldState
from nttd.utils.name_generator import generate_timestamp

if TYPE_CHECKING:
    from nttd.store.recorder import SessionRecorder

logger = logging.getLogger(__name__)

_GS_REFRESH_INTERVAL_REALTIME = 10.0   # seconds between GS refreshes in async_realtime mode
_STAGGER_INTERVAL = 5                  # refresh towns/industries every N cycles

# World changes nobody asked for, which the stored tilemap has to hear about.
#
# nttd sees every contestant action and re-reads what it touched, so that half is covered.
# These three are the game acting on its own, and until now they went unnoticed: an industry
# that opened stood on tiles the map still called empty.
#
# Town GROWTH is not here because OpenTTD raises no event for it. Houses and roads appearing
# as a town expands are left to heal on contact, which costs an agent one refused build per
# stale tile, and that refusal now says why.
_WORLD_CHANGE_EVENTS = frozenset({"industry_open", "industry_close", "town_founded"})

# Slack around the tile an event names. An industry footprint reaches 4 tiles from its
# location and a founded town starts small, so this covers both with room for the access road
# each brings with it.
_WORLD_CHANGE_PAD = 6

# The OpenTTD setting that decides whether a command is served while the game is paused.
# At 3 every command is; at lower levels a build times out AND wedges the script while
# having actually executed. It lives in the shipped openttd.cfg and nothing pins it, so a
# step reads it rather than trusting it.
_PAUSE_LEVEL_SETTING = "construction.command_pause_level"
_PAUSE_LEVEL_ALL_COMMANDS = 3

# OpenTTD's ECONOMY clock advances 1 month per real minute, which is what GSDate
# reports and what every date in nttd refers to. That gives 1 game-day ~ 1.97s,
# measured on OpenTTD 15.3 as 10 game-days per 20.0s (2.00 s/day).
#
# This rate is FIXED. OpenTTD 15.3 has no game_speed setting, and
# economy.minutes_per_calendar_year only moves the separate CALENDAR clock
# (vehicle/house introduction dates), not the economy.
_SECS_PER_GAME_DAY = 1.97
_TIMEOUT_MULTIPLIER = 3.0

# OpenTTD applies a pause a tick after the rcon lands, so a GS refresh issued
# immediately can read a state the game has already moved past.
_PAUSE_SETTLE_SECONDS = 0.2

# How often to poll the game date while waiting for an advance.
_WAIT_POLL_SECONDS = 0.2


class Orchestrator:
    """Controls the runtime loop and broker between the bridge, agents, and GS."""

    def __init__(
        self,
        world: WorldState,
        client: AdminClient,
        recorder: SessionRecorder | None = None,
    ) -> None:
        self.world = world
        self.client = client
        self.recorder = recorder
        self._running = False
        self._heartbeat_interval_days: int = 30
        self._action_window_seconds: float = 5.0
        self._snapshot_interval_days: int = 1
        self._last_snapshot_date: int = -1
        self._observers: list[Any] = []

        # Heartbeat action queue: agents push here during the action window
        self._pending_actions: list[dict[str, Any]] = []
        self._action_deadline: asyncio.Event = asyncio.Event()

        # Assisted mode state machine: idle → waiting → executing → idle

        # Forward GS game events (vehicle crash, subsidy, industry open/close, etc.)
        # to the session recorder so they appear in events.parquet and analysis.
        self.client.on_game_event(self._on_game_event)

        # Optional action tracker (set from app.py)
        self.action_tracker: ActionTracker | None = None
        # Where tile deltas go, set by SessionRuntime. Optional so an orchestrator can be
        # built without a session directory, which the tests do.
        self.tile_writer: Any = None
        self._secs_per_game_day: float = _SECS_PER_GAME_DAY

        # End-condition checker (defaults to disabled; set via load_scenario())
        self._end_checker: EndConditionChecker = EndConditionChecker(EndConditionsConfig())

        # Periodic screenshot/save intervals (wall-clock seconds, 0 = disabled)
        self._screenshot_interval_seconds: float = 60.0
        self._screenshot_type: str = "minimap"  # normal | giant | minimap
        self._save_interval_seconds: float = 0.0
        # Notified when the simulation ends due to an end condition
        self.on_end: list[Any] = []

        # Per-company locks for action serialization (2.5.3)
        self.company_locks: CompanyLockManager = CompanyLockManager()

        # Staggered refresh counter (2.5.6)
        self._refresh_cycle: int = 0

        # Steps taken in stepped mode. Counted here rather than by the caller so a
        # reconnecting contestant cannot restart the count and get a longer run.
        self._step_count: int = 0

        # Whether this game serves commands while paused. Resolved on the first step from
        # the running game, then remembered. See _can_flush_paused.
        self._paused_flush_ok: bool | None = None

    def _on_game_event(self, data: dict[str, Any]) -> None:
        """Handle unsolicited GS game events: refresh what moved, then record it."""
        event_type = str(data.get("event_type", "unknown"))
        # Before the recorder check, deliberately. A session without a recorder still has a
        # stored tilemap that everything else plans over, and tying map freshness to whether
        # the run is being recorded would make the map correct only in scored sessions.
        if event_type in _WORLD_CHANGE_EVENTS:
            self._schedule_world_refresh(event_type, data)
        if not self.recorder:
            return
        company_id = data.get("company_id", data.get("old_company_id"))
        detail_parts: list[str] = []
        for key, val in data.items():
            if key in ("_event", "event_type"):
                continue
            detail_parts.append(f"{key}={val}")
        detail = ", ".join(detail_parts) if detail_parts else ""
        self.recorder.record_event(
            game_date=self.world.game.game_date,
            event_type=event_type,
            company_id=company_id,
            detail=detail,
        )
        logger.info("GS game event: %s %s", event_type, detail)

    def _schedule_world_refresh(self, event_type: str, data: dict[str, Any]) -> None:
        """Queue a re-read of the neighbourhood an autonomous change just named.

        The tilemap is kept current for everything the CONTESTANT does, because nttd sees
        every action and re-reads what it touched, even on failure. The world also changes on
        its own, and that was uncovered: an industry that opened stood on tiles the stored map
        still called empty, and a route planned over them was planned over a fiction.

        Fire and forget, from a synchronous callback on the admin client's own loop, because
        an event is not a request and nothing is waiting on the answer.
        """
        x, y = data.get("x"), data.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            # The subject had already gone when the event fired, so there is no location to
            # read around. Better to skip than to refresh a rectangle around tile 0.
            logger.debug("%s carried no coordinates, so no tiles were refreshed", event_type)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._refresh_around(event_type, x, y))

    async def _refresh_around(self, event_type: str, x: int, y: int) -> None:
        """Re-read one neighbourhood and append it as a delta."""
        if self.tile_writer is None:
            return
        width = self.world.game.map_width or 256
        height = self.world.game.map_height or 256
        area = (
            max(1, x - _WORLD_CHANGE_PAD),
            max(1, y - _WORLD_CHANGE_PAD),
            min(width - 2, x + _WORLD_CHANGE_PAD),
            min(height - 2, y + _WORLD_CHANGE_PAD),
        )
        try:
            tiles = await self._read_tile_area(*area)
            if tiles:
                self.tile_writer.write_delta(tiles)
                logger.info(
                    "Refreshed %d tiles around (%d,%d) after %s",
                    len(tiles), x, y, event_type,
                )
        except Exception:
            logger.debug("Could not refresh tiles after %s", event_type, exc_info=True)

    @property
    def mode(self) -> RuntimeMode:
        return self.world.game.mode

    def load_scenario(self, config: ScenarioConfig) -> None:
        """Apply scenario config to orchestrator (heartbeat interval, action window, end conditions)."""
        self._heartbeat_interval_days = config.heartbeat.interval_days
        self._action_window_seconds = config.heartbeat.action_window_seconds
        self._snapshot_interval_days = config.runtime.snapshot_interval_days
        self._end_checker = EndConditionChecker(config.end_conditions)
        # The economy clock rate is fixed -- there is no game-speed multiplier to
        # scale this by. config.heartbeat.game_speed is retained for config
        # compatibility but has no effect on timing.
        self._secs_per_game_day = _SECS_PER_GAME_DAY
        logger.info(
            "Scenario loaded: %s | heartbeat=%d days | action_window=%.1fs | snapshot_interval=%d days | end_logic=%s",
            config.name,
            config.heartbeat.interval_days,
            config.heartbeat.action_window_seconds,
            config.runtime.snapshot_interval_days,
            config.end_conditions.logic,
        )

    def add_observer(self, callback: Any) -> None:
        self._observers.append(callback)

    def submit_heartbeat_action(self, action: dict[str, Any]) -> None:
        """Submit an action for execution in the current heartbeat window."""
        self._pending_actions.append(action)

    def set_action_window(self, seconds: float) -> None:
        self._action_window_seconds = seconds

    def set_heartbeat_interval(self, days: int) -> None:
        self._heartbeat_interval_days = days

    def stop(self) -> None:
        self._running = False
        self._action_deadline.set()

    async def _notify_observers(self, snapshot: StateSnapshot) -> None:
        for observer in self._observers:
            try:
                result = observer(snapshot)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Observer error")

    async def _capture_screenshot(self) -> None:
        """Fire-and-forget RCON screenshot. Does not block the game loop."""
        try:
            ts = generate_timestamp()
            game_date = self.world.game.game_date
            cmd = f"screenshot {self._screenshot_type} d{game_date}-{ts}"
            asyncio.create_task(self.client.send_rcon(cmd))
            logger.debug("Screenshot requested: %s", cmd)
        except Exception:
            logger.debug("Screenshot request failed (non-critical)")

    async def _capture_save(self, game_date: int, suffix: str = "") -> None:
        """Fire-and-forget interval save, for debugging a run in progress.

        Deliberately unconfirmed and non-blocking: these are a convenience, not
        evidence. The savegame a verifier reloads is captured at session end by
        runtime/final_save.py, which checks that it landed and is readable.
        """
        try:
            ts = generate_timestamp()
            filename = f"d{game_date}-{ts}{suffix}"
            asyncio.create_task(self.client.send_rcon(f"save {filename}"))
            logger.debug("Save requested: %s", filename)
        except Exception:
            logger.debug("Save request failed (non-critical)")

    async def _refresh_world_from_gs(self) -> None:
        """Pull world entities from GS and update WorldState.

        Companies, stations, vehicles are refreshed every cycle.
        Towns and industries are staggered (every N cycles) since they change slowly.
        """
        if not self.client.connected:
            return
        self._refresh_cycle += 1
        try:
            # Towns and industries change slowly: refresh every N cycles
            if self._refresh_cycle % _STAGGER_INTERVAL == 1:
                r = await self.client.send_gamescript("get_towns", timeout=15.0)
                if r.get("success") and isinstance(r.get("result"), list):
                    self.world.apply_gs_towns(r["result"])

                r = await self.client.send_gamescript("get_industries", timeout=15.0)
                if r.get("success") and isinstance(r.get("result"), list):
                    self.world.apply_gs_industries(r["result"])

            # Refresh company roster first: guarantees world.companies is current
            # regardless of whether COMPANY_INFO admin-port events were received.
            r = await self.client.send_gamescript("get_companies", timeout=10.0)
            if r.get("success") and isinstance(r.get("result"), list):
                self.world.apply_gs_companies(r["result"])

            for company in list(self.world.companies.values()):
                if not company.is_active:
                    continue

                r = await self.client.send_gamescript(
                    "get_company_finance", {"company_id": company.id}, timeout=10.0
                )
                if r.get("success") and isinstance(r.get("result"), dict):
                    self.world.apply_gs_company_finance(company.id, r["result"])

                r = await self.client.send_gamescript(
                    "get_stations", {"company_id": company.id}, timeout=15.0
                )
                if r.get("success") and isinstance(r.get("result"), list):
                    self.world.apply_gs_stations(company.id, r["result"])

                r = await self.client.send_gamescript(
                    "get_vehicles", {"company_id": company.id}, timeout=15.0
                )
                if r.get("success") and isinstance(r.get("result"), list):
                    self.world.apply_gs_vehicles(company.id, r["result"])

                r = await self.client.send_gamescript(
                    "get_infrastructure_costs", {"company_id": company.id}, timeout=10.0
                )
                if r.get("success") and isinstance(r.get("result"), dict):
                    self.world.apply_gs_infrastructure(company.id, r["result"])

            # Cargo flows use GSCargoMonitor counters that accumulate between reads.
            # Refresh on staggered cycles (same cadence as towns/industries).
            if self._refresh_cycle % _STAGGER_INTERVAL == 0:
                for company in list(self.world.companies.values()):
                    if not company.is_active:
                        continue
                    r = await self.client.send_gamescript(
                        "get_cargo_flows",
                        {"company_id": company.id, "keep_monitoring": False},
                        timeout=15.0,
                    )
                    if r.get("success") and isinstance(r.get("result"), list):
                        self.world.apply_gs_cargo_flows(company.id, r["result"])

            r = await self.client.send_gamescript("get_subsidies", timeout=10.0)
            if r.get("success") and isinstance(r.get("result"), list):
                self.world.apply_gs_subsidies(r["result"])

        except Exception:
            logger.exception("GS world refresh failed")

    def start_scored_clock(self) -> bool:
        """Start the scored wall-clock. Returns True if this call started it.

        Idempotent, so every action path can call it without checking first. The
        clock deliberately excludes provisioning (map generation, tile capture,
        agent registration), which varies run to run and would otherwise eat
        different amounts of a contestant's budget.
        """
        return self._end_checker.start_clock(self.world.game.game_date)

    # How many tiles one refresh may ask for at a time. get_tile_area REFUSES an area
    # larger than its max_tiles rather than truncating it, so the rectangle is read in row
    # bands that each fit.
    _REFRESH_BAND = 400

    async def _can_flush_paused(self) -> bool:
        """Whether the game will serve build commands while paused.

        True only at construction.command_pause_level = 3, which is what the shipped
        openttd.cfg sets. Asked of the running game rather than assumed, because the setting
        is not in LOCKED_SETTINGS and a scenario could lower it, and the failure at a lower
        level is the bad kind: the command executes, the reply never arrives, and nttd
        records a failure for an action that changed the world.

        Read once per session and remembered. It cannot change mid-run: OpenTTD applies it
        at load and nttd never writes it.
        """
        if self._paused_flush_ok is not None:
            return self._paused_flush_ok
        try:
            reply = await self.client.send_gamescript(
                "get_game_settings",
                {"keys": [_PAUSE_LEVEL_SETTING]},
                timeout=10.0,
            )
            level = (reply.get("result") or {}).get(_PAUSE_LEVEL_SETTING)
        except Exception:
            logger.debug("Could not read %s", _PAUSE_LEVEL_SETTING, exc_info=True)
            level = None
        self._paused_flush_ok = level == _PAUSE_LEVEL_ALL_COMMANDS
        logger.info(
            "%s is %s, so a step %s flush its actions while paused",
            _PAUSE_LEVEL_SETTING, level,
            "will" if self._paused_flush_ok else "will not",
        )
        return self._paused_flush_ok

    async def refresh_changed_tiles(
        self, envelope: ActionEnvelope, outcome: ActionResult,
    ) -> None:
        """Bring the stored map back in step with the world after one action.

        nttd is the only way a contestant changes anything, so it always knows which tiles
        might have moved: the ones the action named, plus the ones a compound build
        reported laying or failing on. Those are re-read and appended as a delta.

        Called from both action paths rather than from one, because a rule kept in two
        places is how the action mapping, the terrain scan and the verifier's world check
        each came to be wrong in this codebase.

        Never fatal. A stale map is a worse map, not a broken run, so a failure here is
        logged and the action still stands.
        """
        if self.tile_writer is None:
            return
        if outcome.status is ActionStatus.REJECTED:
            # Refused before reaching the game, so nothing moved.
            return

        area = affected_area(
            envelope.action_type,
            envelope.parameters or {},
            outcome.changed_entities,
            self.world.game.map_width or 256,
            self.world.game.map_height or 256,
        )
        if area is None:
            return

        try:
            tiles = await self._read_tile_area(*area)
            if tiles:
                self.tile_writer.write_delta(tiles)
        except Exception:
            logger.debug(
                "Could not refresh tiles after %s", envelope.action_type, exc_info=True,
            )

    async def _read_tile_area(
        self, x1: int, y1: int, x2: int, y2: int,
    ) -> list[dict[str, Any]]:
        """Read an inclusive rectangle, in bands that fit one reply.

        get_tile_area's bounds are inclusive, matching what its parameter names suggest.
        They were exclusive, so this asked for one past the end to compensate; that was
        corrected in the handler and here together, since a half-fixed convention is worse
        than either.
        """
        width = x2 - x1 + 1
        if width <= 0:
            return []
        rows_per_band = max(1, self._REFRESH_BAND // width)
        tiles: list[dict[str, Any]] = []
        band_start = y1
        while band_start <= y2:
            band_end = min(band_start + rows_per_band - 1, y2)
            reply = await self.client.send_gamescript(
                "get_tile_area",
                {"x1": x1, "y1": band_start, "x2": x2, "y2": band_end,
                 "max_tiles": self._REFRESH_BAND},
                timeout=20.0,
            )
            band = reply.get("result")
            if not reply.get("success") or not isinstance(band, list):
                logger.debug(
                    "Tile refresh band %d-%d failed: %s",
                    band_start, band_end, reply.get("error"),
                )
                return tiles
            tiles.extend(band)
            band_start = band_end + 1
        return tiles

    def _record_action(
        self, envelope: ActionEnvelope, status: ActionStatus, error: str = "",
        changed: dict[str, Any] | None = None,
    ) -> None:
        """Write an action to the session's audit log.

        The stepped path recorded nothing, so a run driven by steps produced no
        actions.parquet -- and a benchmark cannot be verified from an action log that
        is missing the actions. Refusals are recorded too: reaching for a superhuman
        power is exactly what an auditor wants to see, even though it did not happen.
        """
        if self.recorder is None:
            return
        try:
            self.recorder.record_action(
                envelope=ActionEnvelope(
                    action_id=envelope.action_id,
                    action_type=envelope.action_type,
                    parameters=envelope.parameters,
                    company_id=envelope.company_id,
                    mode=envelope.mode,
                    metadata={
                        **envelope.metadata,
                        "participant_type": "agent",
                        "game_date": self.world.game.game_date,
                        "submitted_at": datetime.now(timezone.utc).isoformat(),
                    },
                ),
                result=ActionResult(
                    action_id=envelope.action_id,
                    status=status,
                    error=error,
                    changed_entities=changed or {},
                ),
            )
        except Exception:
            # The audit trail must not be able to fail the action it describes.
            logger.exception("Could not record action %s", envelope.action_id)

    async def _execute_actions(self, actions: list[dict[str, Any]]) -> list[ActionResult]:
        """Execute a list of GS action dicts, tracking each in ActionTracker.

        Uses per-company locks to serialize same-company actions.

        Returns what happened to each action, in the order submitted. It always knew
        this and used to discard it: every outcome was written to the tracker and to
        actions.parquet and then dropped, so a stepped contestant received an
        observation with no way to tell which of its actions had caused it. Reading the
        world back is not a substitute, because a refusal often changes nothing at all
        and is indistinguishable from an action that was never sent.
        """
        outcomes: list[ActionResult] = []
        # The run is under way once a contestant acts.
        self.start_scored_clock()

        for action in actions:
            gs_action = action.get("action")
            gs_params = action.get("params", {})
            if not gs_action:
                continue

            company_id = gs_params.get("company_id", -1)
            envelope = ActionEnvelope(
                action_id=f"hb_{uuid.uuid4().hex[:8]}",
                company_id=company_id,
                action_type=gs_action,
                parameters=gs_params,
                mode=ActionMode.ATOMIC,
            )
            if self.action_tracker:
                self.action_tracker.submit(envelope)

            # The same admission check the REST path uses. This path previously
            # called send_gamescript directly, so operator-tier commands were
            # reachable in a scored session and left no row in actions.parquet.
            admission = admit(gs_action, company_id)
            if not admission.allowed:
                if self.action_tracker:
                    self.action_tracker.update_result(
                        envelope.action_id, admission.status, admission.error,
                    )
                self._record_action(envelope, admission.status, admission.error)
                logger.info("Action %s refused: %s", gs_action, admission.error)
                outcomes.append(ActionResult(
                    action_id=envelope.action_id,
                    action_type=gs_action,
                    status=admission.status,
                    error=admission.error,
                ))
                continue

            if not self.client.connected:
                if self.action_tracker:
                    self.action_tracker.update_result(
                        envelope.action_id, ActionStatus.FAILED, "Not connected to OpenTTD"
                    )
                self._record_action(
                    envelope, ActionStatus.FAILED, "Not connected to OpenTTD",
                )
                outcomes.append(ActionResult(
                    action_id=envelope.action_id,
                    action_type=gs_action,
                    status=ActionStatus.FAILED,
                    error="Not connected to OpenTTD",
                ))
                continue

            lock = self.company_locks.get_lock(company_id)
            try:
                async with lock:
                    # Pathfinding commands (connect_road, connect_rail) run A*
                    # in the GS and need more time than single-tile actions.
                    timeout = 120.0 if gs_action.startswith("connect_") else 10.0
                    result = await self.client.send_gamescript(gs_action, gs_params, timeout=timeout)
                    # Read by the same function the REST path uses. These were two
                    # copies of one mapping, which is why the stepped path knew nothing
                    # about partial builds or error codes while the other did.
                    outcome = result_from_reply(envelope.action_id, result)
                    if self.action_tracker:
                        self.action_tracker.update_result(
                            envelope.action_id, outcome.status, outcome.error,
                            changed_entities=outcome.changed_entities,
                        )
                    self._record_action(
                        envelope, outcome.status, outcome.error,
                        changed=outcome.changed_entities,
                    )
                    await self.refresh_changed_tiles(envelope, outcome)
                    outcome.action_type = gs_action
                    outcomes.append(outcome)
                    if outcome.status == ActionStatus.SUCCESS:
                        logger.info("Action %s succeeded", gs_action)
                    else:
                        logger.warning(
                            "Action %s %s: %s", gs_action, outcome.status.value, outcome.error,
                        )
            except Exception:
                logger.exception("Failed to execute action: %s", gs_action)
                if self.action_tracker:
                    self.action_tracker.update_result(
                        envelope.action_id, ActionStatus.FAILED, "exception during execution",
                    )
                self._record_action(
                    envelope, ActionStatus.FAILED, "exception during execution",
                )
                outcomes.append(ActionResult(
                    action_id=envelope.action_id,
                    action_type=gs_action,
                    status=ActionStatus.FAILED,
                    error="exception during execution",
                ))

        return outcomes

    # -------------------------------------------------------------------------
    # Stepped mode: client-driven, for RL and ES
    # -------------------------------------------------------------------------

    async def enter_stepped(self) -> StateSnapshot:
        """Pause the game and return the opening observation.

        Stepped mode runs NO loop on the server. The game sits paused between steps,
        so a policy may deliberate for as long as it likes without the world moving --
        which is the entire reason to step rather than play in real time, and the
        reason the heartbeat loop is wrong here: it waits a wall-clock window for
        actions, truncating a slow policy and idling for a fast one.
        """
        self._running = True
        self.world.game.mode = RuntimeMode.STEPPED
        self._step_count = 0
        await self._pause()
        await self._refresh_world_from_gs()
        snapshot = self.world.snapshot()
        if self.recorder:
            self.recorder.record_event(
                self.world.game.game_date, "session_start", detail="stepped",
            )
            self.recorder.record_snapshot(snapshot)
        logger.info(
            "Stepped mode entered at date=%d; the game is paused until the first step",
            snapshot.game.game_date,
        )
        return snapshot

    async def step(
        self, actions: list[dict[str, Any]] | None = None, days: int | None = None,
    ) -> StepResult:
        """Advance one step: flush actions, run the world forward, observe.

        The barrier, in order: the game is already paused, so the batch executes
        against a still world; then it unpauses, advances ``days`` game-days, pauses
        again, and observes. A contestant therefore sees a consistent state and its
        actions land at a known point, neither of which holds if the world moves
        while a batch is part-executed.

        Args:
            actions: The batch to flush, each ``{"action": ..., "params": {...}}``.
                Variable length: a step is not one action. Every one passes the same
                admission check a REST submission does.
            days: Game-days to advance. Defaults to the scenario's heartbeat
                interval, so a scenario sets the step size once.

        Returns:
            A StepResult carrying the post-step observation and whether the run ended.
        """
        advance_days = days if days is not None else self._heartbeat_interval_days

        batch = list(actions or [])

        # The target is fixed BEFORE the world starts moving, so a step advances the
        # same number of days however long its actions took to execute.
        start_date = await self._authoritative_game_date()
        target_date = start_date + advance_days

        # Actions run while the game is PAUSED, so a step costs exactly the days it says.
        #
        # This used to unpause first, on the belief that the GameScript could not serve a
        # command on a paused game. That belief was recorded here from a measurement on
        # 2026-08-12 in which a paused flush wedged the session: every command timed out and
        # the admin stream filled with unparseable packets.
        #
        # The unparseable packets were the cause, not a symptom. Oversized replies were not
        # being chunked, which desynced the stream and lost every later reply; that is issue
        # #60, fixed in 3e99660. Re-measured afterwards on a paused game at
        # construction.command_pause_level = 3:
        #
        #     build_rail_track     success  0.33s
        #     build_rail_station   success  0.32s
        #     build_rail_depot     success  0.36s
        #     connect_rail         success  5.28s, 37 tiles built
        #     get_date afterwards  answered, game_date unmoved at 737790
        #
        # So even the pathfinding actions run paused. Their A* yields through Sleep(1), and
        # under this pause level the SCRIPT still gets ticks while the ECONOMY clock does
        # not, which is the distinction the old comment missed.
        #
        # What this buys is the point of issue #58: a step advances the interval exactly,
        # because no action can consume game time. A slow batch can no longer outrun it.
        #
        # Guarded on the setting rather than trusting it. command_pause_level lives in the
        # shipped openttd.cfg and is not in LOCKED_SETTINGS, so nothing stops a scenario
        # lowering it. At level 1 a paused build times out AND wedges the script while
        # having actually executed, which would record a failure for an action that changed
        # the world. When the level is not 3 this falls back to the old order, which is
        # slower and correct.
        action_results: list[ActionResult] = []
        flush_paused = await self._can_flush_paused()
        if flush_paused and batch:
            action_results = await self._execute_actions(batch)

        await self._unpause()
        if not flush_paused and batch:
            action_results = await self._execute_actions(batch)
        await self._wait_until_game_date(target_date)
        await self._pause()

        await self._refresh_world_from_gs()
        snapshot = self.world.snapshot()
        self._step_count += 1
        if self.recorder:
            self.recorder.record_snapshot(snapshot)

        end_result = self._end_checker.check(snapshot)
        if end_result.triggered:
            logger.info("Simulation ended at step %d: %s", self._step_count, end_result.reason)
            self._running = False
            for callback in self.on_end:
                try:
                    result = callback(end_result.reason)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.exception("on_end callback error")

        return StepResult(
            snapshot=snapshot,
            step=self._step_count,
            # What actually happened, not what was asked for: a slow batch can
            # outrun the interval, and a reader reconstructing the run needs the
            # real figure.
            days_advanced=max(0, snapshot.game.game_date - start_date),
            terminated=end_result.triggered,
            end_reason=end_result.reason if end_result.triggered else "",
            action_results=action_results,
        )

    async def _authoritative_game_date(self) -> int:
        """Ask the GameScript for the current date rather than trusting the cache.

        ``world.game.game_date`` is fed by the admin port's DATE packets, which
        arrive daily and only while the game is running. A value read while paused
        is therefore as old as the pause, and a step that measured its start from it
        reported an advance of 150 days for a 15-day step -- intermittently, which is
        worse than always, because the number looks plausible.

        One round trip, measured at about 0.04s, in exchange for a ``days_advanced``
        that goes into the permanent record. Falls back to the cache if the query
        fails, since a step that cannot read the date should still advance.
        """
        if not self.client.connected:
            return self.world.game.game_date
        try:
            reply = await self.client.send_gamescript("get_date", {}, timeout=10.0)
            date = (reply.get("result") or {}).get("date")
            if isinstance(date, int) and date > 0:
                # Keep the cache in step, so anything else reading it between date
                # packets sees the same value this step was measured from.
                self.world.game.game_date = date
                return date
        except Exception:
            logger.exception("Could not read the game date; using the cached value")
        return self.world.game.game_date

    async def _wait_until_game_date(self, target_date: int) -> None:
        """Block until the world reaches ``target_date``.

        Target-based rather than duration-based, because a step's actions execute
        with the game running and consume game time themselves. ``_wait_game_days``
        measures from whenever it is called, so a step whose batch took ten seconds
        would advance ten seconds further than one whose batch was empty -- and two
        runs of the same scenario would cover different horizons.

        Returns immediately when the target has already passed, which happens when a
        slow batch (pathfinding can take a minute) outruns the step size.
        """
        remaining = target_date - self.world.game.game_date
        if remaining <= 0:
            logger.info(
                "Step actions consumed the whole interval: already at %d, target %d",
                self.world.game.game_date, target_date,
            )
            return

        timeout_s = max(remaining * self._secs_per_game_day * _TIMEOUT_MULTIPLIER, 30.0)
        deadline = timeout_s / _WAIT_POLL_SECONDS
        for _ in range(int(deadline)):
            await asyncio.sleep(_WAIT_POLL_SECONDS)
            if self.world.game.game_date >= target_date or not self._running:
                return
        logger.warning(
            "Timed out after %.0fs waiting for game date %d (now %d)",
            timeout_s, target_date, self.world.game.game_date,
        )


    async def pause_at_start(self) -> None:
        """Freeze the economy clock as soon as a stepped session exists.

        A stepped session used to run unpaused from spawn until the contestant's first
        /step/reset, because enter_stepped is the only thing that pauses and it is reached
        only from that endpoint. Every game day of OpenTTD's boot, the 64,516 tile scan, and
        the contestant's own connect-and-plan latency was charged to the run.

        Measured before this existed: a session declaring 182 steps of one game day reached
        2020-05-29 before reset landed, so 149 of its 182 days were already gone. Two runs of
        the same declared scenario therefore started at different game dates, which is the one
        thing a benchmark cannot allow.

        Safe this early because construction.command_pause_level is 3 in the shipped config:
        the GameScript keeps receiving ticks while the economy clock stands still, so the tile
        scan running concurrently still completes.
        """
        await self._pause()
        self.world.game.mode = RuntimeMode.STEPPED
        logger.info(
            "Stepped session paused at spawn, date=%d; the clock waits for the contestant",
            self.world.game.game_date,
        )

    async def _pause(self) -> None:
        """Pause the game and reflect it in world state."""
        if self.client.connected:
            await self.client.send_rcon("pause")
        self.world.set_paused(True)
        # OpenTTD applies the pause a tick later; without this the first GS refresh
        # can read a state the game has already moved past.
        await asyncio.sleep(_PAUSE_SETTLE_SECONDS)

    async def _unpause(self) -> None:
        if self.client.connected:
            await self.client.send_rcon("unpause")
        self.world.set_paused(False)

    # -------------------------------------------------------------------------
    # Heartbeat mode: server-driven stepping
    # -------------------------------------------------------------------------

    async def run_heartbeat(self, steps: int = 0) -> None:
        """Heartbeat loop: pause → GS refresh → snapshot → action window → execute → unpause → advance.

        Args:
            steps: Number of cycles before stopping. 0 = run indefinitely.
        """
        self._running = True
        step_count = 0
        logger.info(
            "Heartbeat mode started (interval=%d days, action_window=%.1fs)",
            self._heartbeat_interval_days, self._action_window_seconds,
        )
        if self.recorder:
            self.recorder.record_event(self.world.game.game_date, "session_start", detail="heartbeat")

        while self._running:
            # 1. Pause
            if self.client.connected:
                await self.client.send_rcon("pause")
            self.world.set_paused(True)
            await asyncio.sleep(0.2)

            # 2. Refresh world state from GS
            await self._refresh_world_from_gs()

            # 3. Snapshot
            snapshot = self.world.snapshot()
            logger.info(
                "Heartbeat step %d: date=%d, companies=%d, towns=%d, vehicles=%d",
                step_count, snapshot.game.game_date, len(snapshot.companies),
                len(snapshot.towns), len(snapshot.vehicles),
            )
            # Record snapshot to Parquet (heartbeat records every cycle)
            if self.recorder:
                self.recorder.record_snapshot(snapshot)

            # 4. Notify observers (agents receive snapshot, may push heartbeat actions)
            self._pending_actions.clear()
            self._action_deadline.clear()
            await self._notify_observers(snapshot)

            # 4b. Check end conditions (after observers see the snapshot, before acting)
            end_result = self._end_checker.check(snapshot)
            if end_result.triggered:
                logger.info("Simulation ended: %s", end_result.reason)
                for cb in self.on_end:
                    try:
                        result = cb(end_result.reason)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        logger.exception("on_end callback error")
                break

            # 5. Wait for action window
            try:
                await asyncio.wait_for(self._action_deadline.wait(), timeout=self._action_window_seconds)
            except asyncio.TimeoutError:
                pass

            # 6. Execute collected actions
            if self._pending_actions:
                logger.info("Executing %d heartbeat actions", len(self._pending_actions))
                await self._execute_actions(self._pending_actions)
                self._pending_actions.clear()

            # 7. Unpause, advance
            if self.client.connected:
                await self.client.send_rcon("unpause")
            self.world.set_paused(False)

            await self._wait_game_days(self._heartbeat_interval_days)

            step_count += 1
            if steps > 0 and step_count >= steps:
                break

        if self.client.connected:
            await self.client.send_rcon("pause")
        self.world.set_paused(True)
        self._running = False
        if self.recorder:
            self.recorder.record_event(self.world.game.game_date, "session_stop", detail="heartbeat")
        logger.info("Heartbeat mode stopped after %d steps", step_count)

    # -------------------------------------------------------------------------
    # Async real-time mode: human co-play
    # -------------------------------------------------------------------------

    def configure_end_conditions(self, config: EndConditionsConfig) -> None:
        """Set end conditions programmatically (without a full ScenarioConfig)."""
        self._end_checker = EndConditionChecker(config)
        logger.info("End conditions configured: logic=%s", config.logic)

    async def run_async_realtime(self) -> None:
        """Game runs continuously, GS refresh every 10s, snapshots pushed every 2s.

        Also captures periodic minimap screenshots and game saves via RCON.
        End conditions are checked on each snapshot cycle. When triggered,
        the ``on_end`` callbacks fire and the loop exits.
        """
        self._running = True
        logger.info("Async real-time mode started")
        if self.recorder:
            self.recorder.record_event(self.world.game.game_date, "session_start", detail="async_realtime")
        last_gs_refresh = 0.0
        last_screenshot = 0.0
        last_save = 0.0

        while self._running:
            await asyncio.sleep(2.0)
            now = asyncio.get_event_loop().time()

            if now - last_gs_refresh >= _GS_REFRESH_INTERVAL_REALTIME:
                await self._refresh_world_from_gs()
                last_gs_refresh = now

            snapshot = self.world.snapshot()
            await self._notify_observers(snapshot)

            # Record snapshot to Parquet (respecting snapshot_interval_days)
            if self.recorder:
                game_date = snapshot.game.game_date
                if game_date - self._last_snapshot_date >= self._snapshot_interval_days:
                    self.recorder.record_snapshot(snapshot)
                    self._last_snapshot_date = game_date

            # Periodic minimap screenshot
            if self._screenshot_interval_seconds > 0 and self.client.connected:
                if now - last_screenshot >= self._screenshot_interval_seconds:
                    await self._capture_screenshot()
                    last_screenshot = now

            # Periodic game save
            if self._save_interval_seconds > 0 and self.client.connected:
                if now - last_save >= self._save_interval_seconds:
                    game_date = snapshot.game.game_date
                    await self._capture_save(game_date)
                    last_save = now

            # Check end conditions (wall-clock, game date, revenue, cargo)
            end_result = self._end_checker.check(snapshot)
            if end_result.triggered:
                logger.info("Async real-time simulation ended: %s", end_result.reason)
                # Final screenshot only. The final SAVE is captured by
                # stop_session, which every mode ends through -- a "_final" save
                # here would have been a second one under a different name, and it
                # never ran at all for a stepped or manually stopped session.
                if self.client.connected and self._screenshot_interval_seconds > 0:
                    await self._capture_screenshot()
                for cb in self.on_end:
                    try:
                        result = cb(end_result.reason)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        logger.exception("on_end callback error")
                break

        self._running = False
        if self.recorder:
            self.recorder.record_event(self.world.game.game_date, "session_stop", detail="async_realtime")
        logger.info("Async real-time mode stopped")

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _wait_game_days(self, days: int) -> None:
        """Wait until world.game.game_date has advanced by `days`.

        Timeout is days * _SECS_PER_GAME_DAY * _TIMEOUT_MULTIPLIER. At the fixed
        economy rate of 1.97 s/game-day, 30 days ≈ 59s and the 3× multiplier
        gives ~177s of headroom.

        Note this measures from the CURRENT date, so any game time consumed
        before it is called (for example by executing actions) is not counted.
        A stepped mode that must land on an exact horizon should compute its
        target date before acting rather than rely on this helper.
        """
        start_date = self.world.game.game_date
        target_date = start_date + days
        timeout_s = max(days * self._secs_per_game_day * _TIMEOUT_MULTIPLIER, 30.0)
        poll_interval = 0.2
        iterations = int(timeout_s / poll_interval)
        for _ in range(iterations):
            await asyncio.sleep(poll_interval)
            if self.world.game.game_date >= target_date or not self._running:
                return
        logger.warning(
            "Timed out waiting for %d game-days after %.0fs (start=%d, current=%d, target=%d). "
            "Game may be running slower than expected or paused externally.",
            days, timeout_s, start_date, self.world.game.game_date, target_date,
        )


def _needs_game_ticks(batch: list[dict[str, Any]] | None) -> bool:
    """Whether this batch contains an action that cannot execute while paused.

    A module-level function rather than a method because it is a property of the batch
    and nothing else, and because it is the one piece of this worth testing on its own.
    """
    if not batch:
        return False
    return any(
        (entry.get("action") or entry.get("action_type")) in TICK_DEPENDENT_ACTIONS
        for entry in batch
    )
