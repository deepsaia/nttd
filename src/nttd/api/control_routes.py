"""Session-scoped control routes, split by trust tier.

Three routers because these routes are not equally dangerous:

  ``public_router``       reading session status
  ``participant_router``  gameplay: stepping and submitting actions
  ``operator_router``     rcon, save/load, mode, scenario

``router`` aggregates all three so legacy unprefixed paths keep working.
See ``nttd.api.tiers``.
"""

import asyncio
import functools
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import nttd.api.dependencies as deps
from nttd.api.participant_auth import (
    AuthorizationHeader,
    ParticipantToken,
    apply_company_scope,
    extract_token,
    resolve_company_id,
)
from nttd.api.scored_guard import require_unscored
from nttd.runtime.step_errors import (
    AlreadyWaitingAtBarrier,
    NotRegisteredForStepping,
)
from nttd.schemas.game import GameState, RuntimeMode
from nttd.schemas.spend_report import SpendReport
from nttd.schemas.step_result import StepRequest, StepResult

logger = logging.getLogger(__name__)

_SESSION_PREFIX = "/sessions/{session_id}"

public_router = APIRouter(prefix=_SESSION_PREFIX, tags=["control"])
participant_router = APIRouter(prefix=_SESSION_PREFIX, tags=["control"])
operator_router = APIRouter(prefix=_SESSION_PREFIX, tags=["control"])

# Aggregate view used to serve the legacy unprefixed paths.
router = APIRouter()


@public_router.get("/status", response_model=GameState)
def get_status(session_id: str) -> GameState:
    runtime = deps.get_runtime(session_id)
    return runtime.world.game


@participant_router.post("/pause")
async def pause(session_id: str) -> dict[str, bool]:
    runtime = deps.get_runtime(session_id)
    if runtime.admin_client.connected:
        await runtime.admin_client.send_rcon("pause")
    runtime.world.set_paused(True)
    return {"paused": True}


@participant_router.post("/unpause")
async def unpause(session_id: str) -> dict[str, bool]:
    runtime = deps.get_runtime(session_id)
    if runtime.admin_client.connected:
        await runtime.admin_client.send_rcon("unpause")
    runtime.world.set_paused(False)
    return {"paused": False}


@operator_router.post("/speed")
async def set_speed(session_id: str, speed: int) -> dict[str, int]:
    """Rejected: OpenTTD has no runtime game-speed control.

    This endpoint previously issued ``setting game_speed <n>``, which does not
    exist in OpenTTD 15.3 -- the rcon call failed while the endpoint still
    returned ``{"speed": n}``, so callers believed they had changed the pace.

    OpenTTD keeps two clocks. The ECONOMY clock (cargo, payments, finances, and
    everything GSDate reports) is fixed at 1 wall-minute per economy month and
    cannot be changed at all. The CALENDAR clock, which governs vehicle and house
    introduction dates, is set by ``economy.minutes_per_calendar_year`` -- but
    only in wallclock timekeeping and only at map generation, so it belongs in
    the scenario config, not here.
    """
    # Unconditional: the operation does not exist in OpenTTD at all, so session
    # state is irrelevant and resolving it first would only obscure the reason.
    _ = session_id, speed
    raise HTTPException(
        status_code=501,
        detail=(
            "OpenTTD 15.3 has no runtime game-speed setting. The economy clock is "
            "fixed at 1 wall-minute per economy month. To change the calendar pace "
            "(vehicle/house introduction dates), set runtime.timekeeping_units = "
            "'wallclock' and runtime.minutes_per_calendar_year in the scenario "
            "config -- both apply at map generation only."
        ),
    )


@operator_router.post("/mode")
async def set_mode(session_id: str, mode: RuntimeMode) -> dict[str, str]:
    runtime = deps.get_runtime(session_id)

    # Stop existing orchestrator if running
    runtime.orchestrator.stop()
    if runtime.orchestrator_task and not runtime.orchestrator_task.done():
        runtime.orchestrator_task.cancel()
        try:
            await runtime.orchestrator_task
        except asyncio.CancelledError:
            pass

    runtime.world.set_mode(mode)
    runtime.start_orchestrator(mode=mode.value)

    return {"mode": mode.value}


@operator_router.post("/stop")
async def stop_orchestrator(session_id: str) -> dict[str, str]:
    runtime = deps.get_runtime(session_id)
    runtime.orchestrator.stop()
    if runtime.orchestrator_task and not runtime.orchestrator_task.done():
        runtime.orchestrator_task.cancel()
        try:
            await runtime.orchestrator_task
        except asyncio.CancelledError:
            pass
        runtime.orchestrator_task = None
    return {"status": "stopped"}


@participant_router.post("/report")
async def report_spend(
    session_id: str,
    report: SpendReport,
    x_participant_token: ParticipantToken = None,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    """Declare what nttd cannot observe: model, framework, tokens, and cost.

    nttd runs no agent, so these live in the contestant's process. Without this route
    the corresponding result columns were permanently empty -- ``ParticipantReport``
    existed to hold them and nothing ever filled it.

    Recorded as REPORTED, never observed. A contestant could put anything here, which
    is exactly why the result marks the group unverified instead of presenting it
    beside action counts that nttd tallied itself.

    Scoped by token like every other participant route, so a contestant cannot report
    spend against a rival's company. Callable repeatedly: values merge, so a runner
    may declare its model up front and its totals at the end.
    """
    runtime = deps.get_runtime(session_id)
    token = extract_token(x_participant_token, authorization)
    company_id = resolve_company_id(runtime, token)

    runtime.participant_report.declare(
        company_id,
        **{key: value for key, value in report.model_dump().items() if value},
    )
    return {"company_id": company_id, "recorded": "reported"}


@participant_router.post("/step/reset", response_model=StepResult)
async def reset_stepped(
    session_id: str,
    x_participant_token: ParticipantToken = None,
    authorization: AuthorizationHeader = None,
) -> StepResult:
    """Enter stepped mode, register as a stepper, and return the opening observation.

    Idempotent: calling it again re-pauses and re-observes without restarting the
    world. A Gym ``reset`` that begins a NEW episode needs a new session, because a
    session is a run -- rewinding one in place would leave the action log describing
    two episodes as though they were one.

    Registration is what makes multi-company stepping work. The barrier waits for every
    registered stepper before advancing the shared clock, so it has to be told which
    companies are playing; inferring it from the session's company count would stall
    every window on a company whose runner never attached.
    """
    runtime = deps.get_runtime(session_id)
    token = extract_token(x_participant_token, authorization)
    company_id = resolve_company_id(runtime, token, None)
    runtime.step_barrier.register(company_id)

    snapshot = await runtime.orchestrator.enter_stepped()
    return StepResult(
        snapshot=snapshot,
        step=0,
        days_advanced=0,
        steppers=sorted(runtime.step_barrier.registered),
    )


async def _advance_world(
    runtime: Any, days: int | None, batches: list[dict[str, Any]],
) -> StepResult:
    """Advance the shared world once, with every arrived company's actions merged.

    Module level rather than a closure in the route, and given to the barrier as a
    partial: the barrier decides *when* one advance happens, the orchestrator decides
    what an advance is.
    """
    return await runtime.orchestrator.step(actions=batches, days=days)


@participant_router.post("/step", response_model=StepResult)
async def take_step(
    session_id: str,
    request: StepRequest,
    x_participant_token: ParticipantToken = None,
    authorization: AuthorizationHeader = None,
) -> StepResult:
    """Flush a batch of actions, advance the world, and observe.

    The synchronous barrier RL and ES need: the request does not return until the
    world has moved and been re-observed, so a policy never has to guess when its
    actions took effect. The heartbeat loop cannot serve this -- it waits a
    wall-clock window for actions to arrive, which truncates a slow policy and idles
    for a fast one, when the point of stepping is that deliberation is free.

    Every action passes the same admission check a REST submission does.
    """
    runtime = deps.get_runtime(session_id)

    # The company comes from the token, never from the body. Applied to each action
    # so a batch cannot smuggle a rival's company_id past the scope check.
    token = extract_token(x_participant_token, authorization)
    actions: list[dict[str, Any]] = []
    company_id = resolve_company_id(runtime, token, None)
    for entry in request.actions:
        params = dict(entry.get("params") or {})
        apply_company_scope(runtime, params, token)
        actions.append({"action": entry.get("action"), "params": params})

    # The scenario owns the step size for a scored run: letting a contestant pass
    # `days` would let it choose how much world each decision buys.
    days = request.days
    if days is not None and runtime.scored_lock.scored:
        raise HTTPException(
            status_code=403,
            detail=(
                "step size is fixed by the scenario in a scored run: passing `days` "
                "would let a contestant choose how much of the world each decision "
                "buys. Omit it, or use an unscored session to experiment."
            ),
        )

    # partial rather than a closure: the barrier drives the advance, and it needs a
    # callable that takes only the merged batch.
    advance = functools.partial(_advance_world, runtime, days)

    try:
        return await runtime.step_barrier.arrive(company_id, actions, advance)
    except NotRegisteredForStepping as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AlreadyWaitingAtBarrier as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@operator_router.post("/heartbeat/interval")
def set_heartbeat_interval(session_id: str, days: int) -> dict[str, int]:
    runtime = deps.get_runtime(session_id)
    runtime.orchestrator.set_heartbeat_interval(days)
    return {"heartbeat_interval_days": days}


class HeartbeatActionRequest(BaseModel):
    agent_id: str | None = None
    action: str
    params: dict[str, Any] = {}


@participant_router.post("/heartbeat/action")
async def submit_heartbeat_action(
    session_id: str,
    request: HeartbeatActionRequest,
    x_participant_token: ParticipantToken = None,
    authorization: AuthorizationHeader = None,
) -> dict[str, bool]:
    """Submit an action to be executed in the current heartbeat window."""
    runtime = deps.get_runtime(session_id)

    # The company comes from the token. The agent_registry check below predates
    # tokens and was opt-in -- it only ran when the caller volunteered an
    # agent_id, so omitting it bypassed the check entirely.
    params = dict(request.params)
    token = extract_token(x_participant_token, authorization)
    apply_company_scope(runtime, params, token)

    if request.agent_id is not None:
        status = runtime.agent_registry.get(request.agent_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Agent {request.agent_id} not found")
        if status.company_scope and params["company_id"] not in status.company_scope:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Agent {request.agent_id} not authorized for company "
                    f"{params['company_id']}"
                ),
            )

    runtime.orchestrator.submit_heartbeat_action({"action": request.action, "params": params})
    return {"queued": True}


@operator_router.post("/heartbeat/action_window")
def set_action_window(session_id: str, seconds: float) -> dict[str, float]:
    runtime = deps.get_runtime(session_id)
    runtime.orchestrator.set_action_window(seconds)
    return {"action_window_seconds": seconds}


@operator_router.post("/rcon")
async def send_rcon(session_id: str, command: str) -> dict[str, list[str]]:
    runtime = deps.get_runtime(session_id)
    require_unscored(runtime, "rcon", detail=command[:120])
    if not runtime.admin_client.connected:
        return {"response": ["Not connected to OpenTTD"]}
    response = await runtime.admin_client.send_rcon(command)
    return {"response": response}


@operator_router.post("/save")
async def save_game(session_id: str, filename: str = "nttd_save") -> dict[str, Any]:
    """Save the current game to a file."""
    runtime = deps.get_runtime(session_id)
    if not runtime.admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    response = await runtime.admin_client.send_rcon(f"save {filename}")
    return {"filename": filename, "response": response}


@operator_router.post("/load")
async def load_game(session_id: str, filename: str) -> dict[str, Any]:
    """Load a saved game by filename. This will reset the world state."""
    runtime = deps.get_runtime(session_id)
    require_unscored(runtime, "load", detail=filename)
    if not runtime.admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    response = await runtime.admin_client.send_rcon(f"load {filename}")
    return {"filename": filename, "response": response}



@operator_router.post("/scenario")
async def load_scenario(session_id: str, config_path: str | None = None) -> dict[str, Any]:
    """Load scenario from a HOCON config file and apply settings to the orchestrator."""
    from nttd.config import scenario_config  # noqa: PLC0415

    runtime = deps.get_runtime(session_id)
    config = scenario_config.load(config_path)
    runtime.orchestrator.load_scenario(config)

    ec = config.end_conditions
    return {
        "scenario": config.name,
        "description": config.description,
        "heartbeat_interval_days": config.heartbeat.interval_days,
        "action_window_seconds": config.heartbeat.action_window_seconds,
        "game_speed": config.heartbeat.game_speed,
        "end_conditions": {
            "logic": ec.logic,
            "time_limit": {"enabled": ec.time_limit.enabled, "wall_minutes": ec.time_limit.wall_minutes},
            "game_date_limit": {"enabled": ec.game_date_limit.enabled, "end_year": ec.game_date_limit.end_year},
            "revenue_threshold": {
                "enabled": ec.revenue_threshold.enabled,
                "total_revenue": ec.revenue_threshold.total_revenue,
            },
            "cargo_threshold": {
                "enabled": ec.cargo_threshold.enabled,
                "total_cargo_delivered": ec.cargo_threshold.total_cargo_delivered,
            },
            "max_heartbeats": {"enabled": ec.max_heartbeats.enabled, "count": ec.max_heartbeats.count},
        },
    }

# Legacy unprefixed paths (/sessions/{id}/...) are served by aggregating the three
# tier routers. New callers should use the /v1/<tier> prefixes.
router.include_router(public_router)
router.include_router(participant_router)
router.include_router(operator_router)
