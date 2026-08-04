"""Runtime orchestrator — controls heartbeat, async real-time, and assisted modes.

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
from nttd.actions.tracker import ActionTracker
from nttd.bridge.admin_client import AdminClient
from nttd.config.scenario_config import EndConditionsConfig, ScenarioConfig
from nttd.runtime.company_lock import CompanyLockManager
from nttd.runtime.end_conditions import EndConditionChecker
from nttd.runtime.step_errors import StepBatchTooLarge
from nttd.schemas.action_envelope import ActionEnvelope, ActionMode
from nttd.schemas.action_result import ActionResult, ActionStatus
from nttd.schemas.game import RuntimeMode
from nttd.schemas.snapshot import StateSnapshot
from nttd.schemas.step_result import StepResult
from nttd.state.world import WorldState
from nttd.utils.name_generator import generate_timestamp

if TYPE_CHECKING:
    from nttd.db.recorder import SessionRecorder

logger = logging.getLogger(__name__)

_GS_REFRESH_INTERVAL_REALTIME = 10.0   # seconds between GS refreshes in async_realtime mode
_STAGGER_INTERVAL = 5                  # refresh towns/industries every N cycles

# OpenTTD's ECONOMY clock advances 1 month per real minute, which is what GSDate
# reports and what every date in nttd refers to. That gives 1 game-day ≈ 1.97s,
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
        # The session's action budget, set by SessionRuntime. None means unbounded,
        # which is what an orchestrator built without a session should get.
        self.action_budget: Any = None
        self._running = False
        self._heartbeat_interval_days: int = 30
        self._action_window_seconds: float = 5.0
        self._snapshot_interval_days: int = 1
        self._last_snapshot_date: int = -1
        self._observers: list[Any] = []

        # Heartbeat action queue — agents push here during the action window
        self._pending_actions: list[dict[str, Any]] = []
        self._action_deadline: asyncio.Event = asyncio.Event()

        # Assisted mode state machine: idle → waiting → executing → idle
        self._assist_state: str = "idle"
        self._assist_snapshot: StateSnapshot | None = None
        self._assist_ready: asyncio.Event = asyncio.Event()
        self._assist_approved: asyncio.Event = asyncio.Event()
        self._assist_actions: list[dict[str, Any]] = []

        # Forward GS game events (vehicle crash, subsidy, industry open/close, etc.)
        # to the session recorder so they appear in events.parquet and analysis.
        self.client.on_game_event(self._on_game_event)

        # Optional action tracker (set from app.py)
        self.action_tracker: ActionTracker | None = None
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

    def _on_game_event(self, data: dict[str, Any]) -> None:
        """Handle unsolicited GS game events and record them."""
        if not self.recorder:
            return
        event_type = str(data.get("event_type", "unknown"))
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
        self._assist_approved.set()

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
        """Fire-and-forget RCON save. Does not block the game loop."""
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
            # Towns and industries change slowly — refresh every N cycles
            if self._refresh_cycle % _STAGGER_INTERVAL == 1:
                r = await self.client.send_gamescript("get_towns", timeout=15.0)
                if r.get("success") and isinstance(r.get("result"), list):
                    self.world.apply_gs_towns(r["result"])

                r = await self.client.send_gamescript("get_industries", timeout=15.0)
                if r.get("success") and isinstance(r.get("result"), list):
                    self.world.apply_gs_industries(r["result"])

            # Refresh company roster first — guarantees world.companies is current
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

    async def _execute_actions(self, actions: list[dict[str, Any]]) -> None:
        """Execute a list of GS action dicts, tracking each in ActionTracker.

        Uses per-company locks to serialize same-company actions.
        """
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
            admission = admit(gs_action, company_id, budget=self.action_budget)
            if not admission.allowed:
                if self.action_tracker:
                    self.action_tracker.update_result(
                        envelope.action_id, admission.status, admission.error,
                    )
                self._record_action(envelope, admission.status, admission.error)
                logger.info("Action %s refused: %s", gs_action, admission.error)
                continue
            if self.action_budget is not None:
                self.action_budget.consume(company_id)

            if not self.client.connected:
                if self.action_tracker:
                    self.action_tracker.update_result(
                        envelope.action_id, ActionStatus.FAILED, "Not connected to OpenTTD"
                    )
                self._record_action(
                    envelope, ActionStatus.FAILED, "Not connected to OpenTTD",
                )
                continue

            lock = self.company_locks.get_lock(company_id)
            try:
                async with lock:
                    # Pathfinding commands (connect_road, connect_rail) run A*
                    # in the GS and need more time than single-tile actions.
                    timeout = 120.0 if gs_action.startswith("connect_") else 10.0
                    result = await self.client.send_gamescript(gs_action, gs_params, timeout=timeout)
                    if result.get("success"):
                        if self.action_tracker:
                            self.action_tracker.update_result(
                                envelope.action_id, ActionStatus.SUCCESS,
                                changed_entities=result.get("result") or {},
                            )
                        self._record_action(
                            envelope, ActionStatus.SUCCESS,
                            changed=result.get("result") or {},
                        )
                        logger.info("Action %s succeeded", gs_action)
                    else:
                        error = result.get("error", "GS returned failure")
                        if self.action_tracker:
                            self.action_tracker.update_result(
                                envelope.action_id, ActionStatus.FAILED, error,
                            )
                        self._record_action(envelope, ActionStatus.FAILED, error)
                        logger.warning("Action %s failed: %s", gs_action, error)
            except Exception:
                logger.exception("Failed to execute action: %s", gs_action)
                if self.action_tracker:
                    self.action_tracker.update_result(
                        envelope.action_id, ActionStatus.FAILED, "exception during execution",
                    )
                self._record_action(
                    envelope, ActionStatus.FAILED, "exception during execution",
                )

    # -------------------------------------------------------------------------
    # Stepped mode — client-driven, for RL and ES
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
        if batch:
            # The ceiling applies to the BATCH, checked once before anything runs.
            # _execute_actions admits each action individually with count=1, so a
            # 16-action batch passed sixteen checks of one and the per-submission
            # ceiling never saw it -- verified: 16/16 allowed against a limit of 15.
            # Refused whole rather than truncated: a policy that planned a route as
            # one batch should not have it half-built.
            self._check_batch_size(batch)

        # The target is fixed BEFORE the world starts moving, so a step advances the
        # same number of days however long its actions took to execute.
        start_date = await self._authoritative_game_date()
        target_date = start_date + advance_days

        # Actions run with the game RUNNING, not paused.
        #
        # Not because single-tile builds need it: at construction.command_pause_level
        # = 3 a paused build_road_stop returns success in 0.1s. It is the PATHFINDING
        # actions. The A* loop yields every 500 iterations through
        # _YieldAndProcessEvents (main.nut:1912, :2414), whose first statement is
        # Sleep(1) -- and Sleep counts GAME TICKS, of which a paused game delivers
        # none. So connect_road and connect_rail hang while paused, at any pause
        # level, once the search is long enough to reach that yield.
        #
        # Length is what decides it, which is why this cannot be worked around by
        # inspecting the action: a SHORT connection never yields and succeeds while
        # paused in 0.0s, while a cross-map one times out. Whether a given
        # connect_road deadlocks is not knowable before running it, so the flush
        # simply always sits between the unpause and the advance. These are the
        # workhorse actions; a design that could not issue them would not be a
        # design.
        #
        # This also keeps the flush safe if the pause level is ever lowered: at
        # level 1 a paused build times out AND wedges the GameScript, while having
        # actually executed -- so nttd would record a failure for an action that
        # mutated the world.
        await self._unpause()
        if batch:
            await self._execute_actions(batch)
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

    def _check_batch_size(self, batch: list[dict[str, Any]]) -> None:
        """Refuse an over-ceiling batch before any of it executes.

        Separate from the per-action gate because the two ask different questions.
        The gate asks "may this action be taken at all"; this asks "is this
        submission too big", which is a property of the batch and invisible when each
        action is checked alone.

        Raises:
            StepBatchTooLarge: with the same wording the REST batch route uses, so a
                contestant hitting the ceiling gets one explanation regardless of
                which path it used.
        """
        if self.action_budget is None:
            return
        company_id = int((batch[0].get("params") or {}).get("company_id", -1))
        decision = self.action_budget.check(company_id, count=len(batch))
        if not decision.allowed:
            logger.info("Step batch refused: %s", decision.reason)
            for entry in batch:
                envelope = ActionEnvelope(
                    action_id=f"hb_{uuid.uuid4().hex[:8]}",
                    company_id=company_id,
                    action_type=str(entry.get("action") or "unknown"),
                    parameters=dict(entry.get("params") or {}),
                    mode=ActionMode.ATOMIC,
                )
                self._record_action(
                    envelope, ActionStatus.BLOCKED,
                    f"Action budget exceeded: {decision.reason}",
                )
            raise StepBatchTooLarge(f"Action budget exceeded: {decision.reason}")

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
    # Heartbeat mode — server-driven stepping
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
    # Async real-time mode — human co-play
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
                # Final screenshot and save before ending (only if enabled)
                if self.client.connected:
                    if self._screenshot_interval_seconds > 0:
                        await self._capture_screenshot()
                    if self._save_interval_seconds > 0:
                        await self._capture_save(snapshot.game.game_date, suffix="_final")
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
    # Assisted mode — human-triggered AI
    # -------------------------------------------------------------------------

    async def trigger_assist(self) -> StateSnapshot:
        """Pause the game, refresh state, and return a snapshot for human review.

        The game stays paused until approve_assist() or cancel_assist() is called.
        """
        self._assist_state = "waiting"
        self._assist_ready.clear()
        self._assist_approved.clear()

        if self.client.connected:
            await self.client.send_rcon("pause")
        self.world.set_paused(True)

        await self._refresh_world_from_gs()
        self._assist_snapshot = self.world.snapshot()

        self._assist_state = "ready"
        return self._assist_snapshot

    async def approve_assist(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute the approved action list and unpause."""
        if self._assist_state != "ready":
            return [{"error": "No active assist session"}]

        self._assist_state = "executing"
        self._assist_actions = actions

        results = []
        for action in actions:
            gs_action = action.get("action")
            gs_params = action.get("params", {})
            if gs_action and self.client.connected:
                timeout = 120.0 if gs_action.startswith("connect_") else 10.0
                result = await self.client.send_gamescript(gs_action, gs_params, timeout=timeout)
                results.append({"action": gs_action, "result": result})

        if self.client.connected:
            await self.client.send_rcon("unpause")
        self.world.set_paused(False)
        self._assist_state = "idle"
        return results

    async def cancel_assist(self) -> None:
        """Cancel the assist session and unpause without executing anything."""
        self._assist_state = "idle"
        if self.client.connected:
            await self.client.send_rcon("unpause")
        self.world.set_paused(False)

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
