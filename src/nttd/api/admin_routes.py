"""Admin API endpoints for session management, player management, and deity operations.

Each session is its own OpenTTD server. Starting a session spawns a server process;
stopping it kills the process. All operations target a specific session's runtime.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import nttd.api.dependencies as deps
from nttd.api.scored_guard import require_unscored
from nttd.db.repositories import session_repo
from nttd.utils.name_generator import generate_session_name

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    name: str = ""
    settings: dict[str, str] = {}
    config_path: str = ""


class UpdateSettingsRequest(BaseModel):
    settings: dict[str, str]


class StartSessionRequest(BaseModel):
    mode: str = "newgame"
    savefile: str | None = None
    ai_opponents: int = 0
    agent_companies: int = 0
    # Company names by company_id, as strings since JSON object keys are strings.
    # Any company omitted here gets a generated name like 'jade-heron-4f2a'.
    company_names: dict[str, str] | None = None


class EndConditionsRequest(BaseModel):
    """End conditions for a session. Only the fields supplied are enabled."""

    logic: str = "any"
    wall_minutes: float | None = None
    end_year: int | None = None
    revenue_threshold: int | None = None
    cargo_threshold: int | None = None
    # Bounds a run in steps rather than wall time -- the natural bound for
    # stepped mode, where deliberation time is unbounded.
    max_heartbeats: int | None = None
    # Ends the run if a scored company goes bankrupt or is removed.
    bankruptcy: bool = False


class DeityBalanceRequest(BaseModel):
    company_id: int
    delta: int
    expense_type: int | None = None


class DeityMaxLoanRequest(BaseModel):
    company_id: int
    amount: int


class DeitySettingRequest(BaseModel):
    key: str
    value: int


class DeityTownRequest(BaseModel):
    town_id: int | None = None
    x: int | None = None
    y: int | None = None
    size: int = 1
    city: bool = False
    layout: int = 0
    name: str = ""
    growth_rate: int | None = None
    amount: int | None = None


class DeitySubsidyRequest(BaseModel):
    cargo_id: int
    src_type: int
    src_id: int
    dst_type: int
    dst_id: int


class DeityTownRatingRequest(BaseModel):
    town_id: int
    company_id: int
    delta: int


# Settings keys a client must never supply. These decide whether a run is scored and
# what limits bind it, so accepting them from a request body would undo the point of
# moving the limits off AgentConfig: POST /admin/sessions/new with
# {"_scored": "0"} disabled the lock outright, and {"_fair_max_actions": "200"}
# raised the budget. They may only come from scenario_to_settings.
_PROTECTED_SETTING_PREFIXES = ("_scored", "_fair_", "_task_id", "_settings_digest")


def _reject_protected_settings(settings: dict[str, str]) -> None:
    """Raise 400 if a request tries to set a scenario-owned key.

    Refused rather than ignored: a caller that believes it disabled scoring should
    be told, not silently overruled.
    """
    offenders = sorted(
        key for key in settings
        if key.startswith(_PROTECTED_SETTING_PREFIXES)
    )
    if offenders:
        raise HTTPException(
            status_code=400,
            detail=(
                f"These settings are owned by the scenario and cannot be supplied by "
                f"a client: {', '.join(offenders)}. They decide whether the run is "
                f"scored and what limits bind it, so set them in the scenario file."
            ),
        )


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

@router.post("/sessions/new")
async def create_session(request: CreateSessionRequest) -> dict[str, Any]:
    name = request.name or generate_session_name()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"ses_{ts}_{uuid.uuid4().hex[:8]}"

    # If config_path provided, load and convert to settings
    _reject_protected_settings(request.settings)
    settings = dict(request.settings)
    if request.config_path:
        from nttd.config.scenario_config import load as load_scenario
        from nttd.config.scenario_config import scenario_to_settings

        cfg = load_scenario(request.config_path)
        config_settings = scenario_to_settings(cfg)
        # Explicit settings override config-derived ones
        config_settings.update(settings)
        settings = config_settings

    meta: dict[str, str] = {}
    if request.config_path:
        meta["config_path"] = request.config_path

    await session_repo.create_session(
        session_id=session_id,
        name=name,
        status="pending",
        meta=meta or None,
    )

    if settings:
        await session_repo.upsert_settings(session_id, settings)

    return {"session_id": session_id, "status": "pending"}


@router.get("/sessions")
async def list_sessions(status: str | None = None, include_archived: bool = True, limit: int = 50) -> dict[str, Any]:
    sessions = await session_repo.list_sessions(status=status, include_archived=include_archived, limit=limit)

    # Enrich with running state from session manager
    mgr = deps.session_manager
    for s in sessions:
        sid = s.get("session_id")
        if mgr and sid:
            rt = mgr.get_runtime(sid)
            s["running"] = rt is not None and rt.connected
        else:
            s["running"] = False

    return {"sessions": sessions, "count": len(sessions)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = await session_repo.get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    settings = await session_repo.get_settings(session_id)

    # Add runtime state
    mgr = deps.session_manager
    runtime = mgr.get_runtime(session_id) if mgr else None
    running = runtime is not None and runtime.connected

    # From the live token registry, not from agents.conf. That file was written by
    # the deleted server-driven gameloop, so this field was always an empty list.
    participants = (
        [{"company_id": p.company_id} for p in runtime.participants.participants()]
        if runtime is not None else []
    )

    return {
        **session,
        "settings": settings,
        "participants": participants,
        "running": running,
    }


@router.post("/sessions/{session_id}/settings")
async def update_settings(session_id: str, request: UpdateSettingsRequest) -> dict[str, Any]:
    session = await session_repo.get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    _reject_protected_settings(request.settings)
    await session_repo.upsert_settings(session_id, request.settings)

    # Apply live to running session
    mgr = deps.session_manager
    runtime = mgr.get_runtime(session_id) if mgr else None
    applied = False
    if runtime and runtime.connected:
        # Rewriting settings mid-run changes the task instance itself, so a scored
        # session refuses it. Storing them above is harmless: they only take effect
        # on the next start.
        require_unscored(runtime, "settings/apply_live")
        for key, value in request.settings.items():
            await runtime.admin_client.send_rcon(f"setting {key} {value}")
        applied = True

    return {"session_id": session_id, "settings": request.settings, "applied": applied}


@router.post("/sessions/{session_id}/start")
async def start_session(session_id: str, request: StartSessionRequest) -> dict[str, Any]:
    session = await session_repo.get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    mgr = deps.session_manager
    if mgr is None:
        raise HTTPException(status_code=503, detail="Session manager not ready")

    if mgr.get_runtime(session_id):
        raise HTTPException(status_code=409, detail="Session is already running")

    # Get stored settings
    settings = await session_repo.get_settings(session_id)

    # JSON object keys are strings, so company ids arrive as strings.
    try:
        company_names = (
            {int(cid): name for cid, name in request.company_names.items()}
            if request.company_names else None
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"company_names keys must be integer company ids: {e}",
        ) from e

    # Start the OpenTTD server (spawns process, connects admin client)
    try:
        runtime = await mgr.start_session(
            session_id, settings,
            ai_opponents=request.ai_opponents,
            agent_companies=request.agent_companies,
            company_names=company_names,
        )
    except Exception as e:
        logger.exception("Failed to start session %s", session_id)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {
        "session_id": session_id,
        "status": "active",
        "game_port": runtime.game_port,
        "admin_port": runtime.admin_port,
        "pid": runtime.process.pid if runtime.process else None,
        # One token per contestant company. Pass as X-Participant-Token (or
        # Authorization: Bearer) on action requests; the company acted upon is
        # derived from the token, never from the request body. Also written to
        # <session_dir>/participants.json for separately launched agents.
        "participants": [
            {"company_id": p.company_id, "token": p.token}
            for p in runtime.participants.participants()
        ],
    }


@router.get("/sessions/{session_id}/participants")
async def list_session_participants(session_id: str) -> dict[str, Any]:
    """List the participant tokens issued for a running session.

    Operator tier, because it returns every company's token rather than the caller's
    own. That is a discoverability boundary, not a security one -- the same tokens
    sit in ``<session_dir>/participants.json`` beside whatever is running -- but a
    route that hands out all of them should still not be participant-facing.

    Exists because tokens were previously returned only in the response to
    ``/start``. A contestant who lost that output, or who attached to a session
    someone else started, had to go and read a file off disk.
    """
    runtime = deps.get_runtime(session_id)
    return {
        "session_id": session_id,
        "participants": [
            {"company_id": p.company_id, "token": p.token}
            for p in runtime.participants.participants()
        ],
    }


@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str, end_reason: str = "manual") -> dict[str, Any]:
    session = await session_repo.get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    mgr = deps.session_manager
    if mgr:
        await mgr.stop_session(session_id, end_reason=end_reason)

    # Auto-archive on stop
    await session_repo.archive_session(session_id)

    return {"session_id": session_id, "status": "archived", "end_reason": end_reason}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    session = await session_repo.get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Stop if running
    mgr = deps.session_manager
    if mgr and mgr.get_runtime(session_id):
        await mgr.stop_session(session_id, end_reason="deleted")

    await session_repo.delete_session(session_id)
    return {"session_id": session_id, "status": "deleted"}


# ---------------------------------------------------------------------------
# Session-scoped: Player / client management
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/clients")
async def get_clients(session_id: str) -> dict[str, Any]:
    runtime = deps.get_runtime(session_id)
    result = await runtime.admin_client.send_gamescript("get_clients")
    if result.get("success"):
        return {"clients": result.get("result", []), "connected": True}
    return {"clients": [], "connected": True, "error": result.get("error")}


@router.post("/sessions/{session_id}/clients/{client_id}/move")
async def move_client(session_id: str, client_id: int, company_id: int) -> dict[str, Any]:
    runtime = deps.get_runtime(session_id)
    response = await runtime.admin_client.send_rcon(f"move {client_id} {company_id}")
    return {"client_id": client_id, "company_id": company_id, "response": response}


@router.post("/sessions/{session_id}/clients/{client_id}/kick")
async def kick_client(session_id: str, client_id: int, reason: str = "") -> dict[str, Any]:
    runtime = deps.get_runtime(session_id)
    cmd = f"kick {client_id}" + (f" {reason}" if reason else "")
    response = await runtime.admin_client.send_rcon(cmd)
    return {"client_id": client_id, "response": response}


@router.get("/sessions/{session_id}/spectators")
async def get_spectators(session_id: str) -> dict[str, Any]:
    runtime = deps.get_runtime(session_id)
    result = await runtime.admin_client.send_gamescript("get_clients")
    if result.get("success"):
        spectators = [c for c in result.get("result", []) if c.get("company_id") == 255]
        return {"spectators": spectators}
    return {"spectators": []}


# ---------------------------------------------------------------------------
# Session-scoped: Deity operations
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/deity/change_balance")
async def deity_change_balance(session_id: str, request: DeityBalanceRequest) -> dict[str, Any]:
    runtime = deps.get_runtime(session_id)
    require_unscored(runtime, "deity/change_balance")
    params: dict[str, Any] = {"company_id": request.company_id, "delta": request.delta}
    if request.expense_type is not None:
        params["expense_type"] = request.expense_type
    result = await runtime.admin_client.send_gamescript("change_bank_balance", params)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/sessions/{session_id}/deity/set_max_loan")
async def deity_set_max_loan(session_id: str, request: DeityMaxLoanRequest) -> dict[str, Any]:
    runtime = deps.get_runtime(session_id)
    require_unscored(runtime, "deity/set_max_loan")
    result = await runtime.admin_client.send_gamescript(
        "set_max_loan", {"company_id": request.company_id, "amount": request.amount}
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/sessions/{session_id}/deity/set_setting")
async def deity_set_setting(session_id: str, request: DeitySettingRequest) -> dict[str, Any]:
    runtime = deps.get_runtime(session_id)
    require_unscored(runtime, "deity/set_setting")
    result = await runtime.admin_client.send_gamescript(
        "set_game_setting", {"key": request.key, "value": request.value}
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/sessions/{session_id}/deity/found_town")
async def deity_found_town(session_id: str, request: DeityTownRequest) -> dict[str, Any]:
    runtime = deps.get_runtime(session_id)
    require_unscored(runtime, "deity/found_town")
    params: dict[str, Any] = {}
    if request.x is not None and request.y is not None:
        params["x"] = request.x
        params["y"] = request.y
    params["size"] = request.size
    params["city"] = request.city
    params["layout"] = request.layout
    if request.name:
        params["name"] = request.name
    result = await runtime.admin_client.send_gamescript("found_town", params)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/sessions/{session_id}/deity/expand_town")
async def deity_expand_town(session_id: str, request: DeityTownRequest) -> dict[str, Any]:
    runtime = deps.get_runtime(session_id)
    require_unscored(runtime, "deity/expand_town")
    if request.town_id is None:
        raise HTTPException(status_code=400, detail="town_id required")
    params: dict[str, Any] = {"town_id": request.town_id}
    if request.amount is not None:
        params["times"] = request.amount
    result = await runtime.admin_client.send_gamescript("expand_town", params)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/sessions/{session_id}/deity/set_town_growth")
async def deity_set_town_growth(session_id: str, request: DeityTownRequest) -> dict[str, Any]:
    runtime = deps.get_runtime(session_id)
    require_unscored(runtime, "deity/set_town_growth")
    if request.town_id is None or request.growth_rate is None:
        raise HTTPException(status_code=400, detail="town_id and growth_rate required")
    result = await runtime.admin_client.send_gamescript(
        "set_town_growth", {"town_id": request.town_id, "days_between_growth": request.growth_rate}
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/sessions/{session_id}/deity/create_subsidy")
async def deity_create_subsidy(session_id: str, request: DeitySubsidyRequest) -> dict[str, Any]:
    runtime = deps.get_runtime(session_id)
    require_unscored(runtime, "deity/create_subsidy")
    result = await runtime.admin_client.send_gamescript("create_subsidy", {
        "cargo_id": request.cargo_id,
        "src_type": request.src_type,
        "src_id": request.src_id,
        "dst_type": request.dst_type,
        "dst_id": request.dst_id,
    })
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/sessions/{session_id}/deity/change_town_rating")
async def deity_change_town_rating(session_id: str, request: DeityTownRatingRequest) -> dict[str, Any]:
    runtime = deps.get_runtime(session_id)
    require_unscored(runtime, "deity/change_town_rating")
    result = await runtime.admin_client.send_gamescript("change_town_rating", {
        "town_id": request.town_id,
        "company_id": request.company_id,
        "delta": request.delta,
    })
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


# ---------------------------------------------------------------------------
# Session-scoped: Pathfinding
# ---------------------------------------------------------------------------

class PathfindRequest(BaseModel):
    from_x: int
    from_y: int
    to_x: int
    to_y: int
    transport_type: str = "road"
    company_id: int = -1
    avoid_demolish: bool = False
    max_iterations: int = 50_000
    corridor_margin: int = 10


@router.post("/sessions/{session_id}/pathfind")
async def run_pathfind(session_id: str, request: PathfindRequest) -> dict[str, Any]:
    from nttd.pathfinding import service as pf_service  # noqa: PLC0415

    runtime = deps.get_runtime(session_id)

    if pf_service.get_cache() is None:
        if runtime.world.game.map_width > 0 and runtime.world.game.map_height > 0:
            pf_service.init_cache(runtime.world.game.map_width, runtime.world.game.map_height)
        else:
            raise HTTPException(status_code=503, detail="Map dimensions not available yet")

    result = await pf_service.pathfind(
        from_x=request.from_x,
        from_y=request.from_y,
        to_x=request.to_x,
        to_y=request.to_y,
        transport_type=request.transport_type,
        gs_client=runtime.admin_client,
        company_id=request.company_id,
        avoid_demolish=request.avoid_demolish,
        max_iterations=request.max_iterations,
        corridor_margin=request.corridor_margin,
    )
    return result


# ---------------------------------------------------------------------------
# Session-scoped: End conditions
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/end-conditions")
async def set_end_conditions(session_id: str, request: EndConditionsRequest) -> dict[str, Any]:
    """Configure end conditions on a running session's orchestrator."""
    from nttd.config.scenario_config import (  # noqa: PLC0415
        BankruptcyConfig,
        CargoThresholdConfig,
        EndConditionsConfig,
        GameDateLimitConfig,
        MaxHeartbeatsConfig,
        RevenueThresholdConfig,
        TimeLimitConfig,
    )

    runtime = deps.get_runtime(session_id)

    # time_limit defaults to enabled, so it is explicitly disabled first: a
    # caller that omits wall_minutes must not silently get a 60-minute cap.
    config = EndConditionsConfig(logic=request.logic, time_limit=TimeLimitConfig(enabled=False))
    if request.wall_minutes is not None:
        config.time_limit = TimeLimitConfig(enabled=True, wall_minutes=request.wall_minutes)
    if request.end_year is not None:
        config.game_date_limit = GameDateLimitConfig(enabled=True, end_year=request.end_year)
    if request.revenue_threshold is not None:
        config.revenue_threshold = RevenueThresholdConfig(enabled=True, total_revenue=request.revenue_threshold)
    if request.cargo_threshold is not None:
        config.cargo_threshold = CargoThresholdConfig(enabled=True, total_cargo_delivered=request.cargo_threshold)
    if request.max_heartbeats is not None:
        config.max_heartbeats = MaxHeartbeatsConfig(enabled=True, count=request.max_heartbeats)
    if request.bankruptcy:
        config.bankruptcy = BankruptcyConfig(enabled=True)

    runtime.orchestrator.configure_end_conditions(config)

    tl = config.time_limit
    gd = config.game_date_limit
    rv = config.revenue_threshold
    ct = config.cargo_threshold
    return {
        "session_id": session_id,
        "end_conditions": {
            "logic": config.logic,
            "time_limit": {"enabled": tl.enabled, "wall_minutes": tl.wall_minutes},
            "game_date_limit": {"enabled": gd.enabled, "end_year": gd.end_year},
            "revenue_threshold": {"enabled": rv.enabled, "total_revenue": rv.total_revenue},
            "cargo_threshold": {"enabled": ct.enabled, "total_cargo_delivered": ct.total_cargo_delivered},
        },
    }
