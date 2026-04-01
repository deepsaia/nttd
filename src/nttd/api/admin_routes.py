"""Admin API endpoints for session management, player management, and deity operations.

Ref: docs/openttd_study_part4_multiplayer_agent_design.md §11
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nttd.api.dependencies import admin_client, orchestrator, world
from nttd.db.repositories import session_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    name: str = ""
    settings: dict[str, str] = {}


class UpdateSettingsRequest(BaseModel):
    settings: dict[str, str]


class StartSessionRequest(BaseModel):
    mode: str = "newgame"
    savefile: str | None = None
    ai_opponents: int = 0


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


# ---------------------------------------------------------------------------
# 2.3.1-2.3.7: Session management
# ---------------------------------------------------------------------------

@router.post("/sessions/new")
async def create_session(request: CreateSessionRequest) -> dict[str, Any]:
    session_id = f"ses_{uuid.uuid4().hex[:12]}"
    game_date = world.game.game_date if world.game.game_date > 0 else None

    await session_repo.create_session(
        session_id=session_id,
        name=request.name or f"Session {session_id[:8]}",
        game_start_date=game_date,
    )

    if request.settings:
        await session_repo.upsert_settings(session_id, request.settings)

    return {"session_id": session_id, "status": "active"}


@router.get("/sessions")
async def list_sessions(status: str | None = None, limit: int = 50) -> dict[str, Any]:
    sessions = await session_repo.list_sessions(status=status, limit=limit)
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = await session_repo.get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    settings = await session_repo.get_settings(session_id)
    participants = await session_repo.list_participants(session_id)

    return {**session, "settings": settings, "participants": participants}


@router.post("/sessions/{session_id}/settings")
async def update_settings(session_id: str, request: UpdateSettingsRequest) -> dict[str, Any]:
    session = await session_repo.get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    await session_repo.upsert_settings(session_id, request.settings)

    # Apply settings to OpenTTD via rcon if connected
    if admin_client.connected:
        for key, value in request.settings.items():
            await admin_client.send_rcon(f"setting {key} {value}")

    return {"session_id": session_id, "settings": request.settings, "applied": admin_client.connected}


@router.post("/sessions/{session_id}/start")
async def start_session(session_id: str, request: StartSessionRequest) -> dict[str, Any]:
    session = await session_repo.get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")

    # Apply stored settings via rcon
    settings = await session_repo.get_settings(session_id)
    for key, value in settings.items():
        await admin_client.send_rcon(f"setting {key} {value}")

    # Start AI opponents
    if request.ai_opponents > 0:
        await admin_client.send_rcon("setting ai_in_multiplayer true")
        await admin_client.send_rcon(f"setting max_no_competitors {request.ai_opponents}")

    # Start game
    if request.mode == "newgame":
        response = await admin_client.send_rcon("newgame")
    elif request.mode == "load" and request.savefile:
        response = await admin_client.send_rcon(f"load {request.savefile}")
    else:
        response = ["Game already running"]

    return {"session_id": session_id, "mode": request.mode, "response": response}


@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str, end_reason: str = "manual") -> dict[str, Any]:
    session = await session_repo.get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    game_date = world.game.game_date if world.game.game_date > 0 else None

    orchestrator.stop()
    await session_repo.end_session(
        session_id=session_id,
        end_reason=end_reason,
        game_end_date=game_date,
    )

    if admin_client.connected:
        await admin_client.send_rcon("pause")

    return {"session_id": session_id, "status": "ended", "end_reason": end_reason}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    session = await session_repo.get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Mark as archived rather than deleting data
    await session_repo.end_session(session_id=session_id, end_reason="archived")
    return {"session_id": session_id, "status": "archived"}


# ---------------------------------------------------------------------------
# 2.3.8-2.3.13: Player / agent management
# ---------------------------------------------------------------------------

@router.get("/clients")
async def get_clients() -> dict[str, Any]:
    """List connected game clients via GS get_clients command."""
    if not admin_client.connected:
        return {"clients": [], "connected": False}

    result = await admin_client.send_gamescript("get_clients")
    if result.get("success"):
        return {"clients": result.get("result", []), "connected": True}
    return {"clients": [], "connected": True, "error": result.get("error")}


@router.post("/clients/{client_id}/move")
async def move_client(client_id: int, company_id: int) -> dict[str, Any]:
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    response = await admin_client.send_rcon(f"move {client_id} {company_id}")
    return {"client_id": client_id, "company_id": company_id, "response": response}


@router.post("/clients/{client_id}/kick")
async def kick_client(client_id: int, reason: str = "") -> dict[str, Any]:
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    cmd = f"kick {client_id}" + (f" {reason}" if reason else "")
    response = await admin_client.send_rcon(cmd)
    return {"client_id": client_id, "response": response}


@router.get("/spectators")
async def get_spectators() -> dict[str, Any]:
    """List spectators (clients with company_id=255)."""
    if not admin_client.connected:
        return {"spectators": []}

    result = await admin_client.send_gamescript("get_clients")
    if result.get("success"):
        spectators = [c for c in result.get("result", []) if c.get("company_id") == 255]
        return {"spectators": spectators}
    return {"spectators": []}


# ---------------------------------------------------------------------------
# 2.3.14-2.3.21: Deity operations
# ---------------------------------------------------------------------------

@router.post("/deity/change_balance")
async def deity_change_balance(request: DeityBalanceRequest) -> dict[str, Any]:
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")

    params: dict[str, Any] = {"company_id": request.company_id, "delta": request.delta}
    if request.expense_type is not None:
        params["expense_type"] = request.expense_type

    result = await admin_client.send_gamescript("change_bank_balance", params)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/deity/set_max_loan")
async def deity_set_max_loan(request: DeityMaxLoanRequest) -> dict[str, Any]:
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")

    result = await admin_client.send_gamescript(
        "set_max_loan", {"company_id": request.company_id, "amount": request.amount}
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/deity/set_setting")
async def deity_set_setting(request: DeitySettingRequest) -> dict[str, Any]:
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")

    result = await admin_client.send_gamescript(
        "set_game_setting", {"key": request.key, "value": request.value}
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/deity/found_town")
async def deity_found_town(request: DeityTownRequest) -> dict[str, Any]:
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")

    params: dict[str, Any] = {}
    if request.x is not None and request.y is not None:
        params["x"] = request.x
        params["y"] = request.y
    params["size"] = request.size
    params["city"] = request.city
    params["layout"] = request.layout
    if request.name:
        params["name"] = request.name

    result = await admin_client.send_gamescript("found_town", params)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/deity/expand_town")
async def deity_expand_town(request: DeityTownRequest) -> dict[str, Any]:
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")

    if request.town_id is None:
        raise HTTPException(status_code=400, detail="town_id required")

    params: dict[str, Any] = {"town_id": request.town_id}
    if request.amount is not None:
        params["times"] = request.amount

    result = await admin_client.send_gamescript("expand_town", params)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/deity/set_town_growth")
async def deity_set_town_growth(request: DeityTownRequest) -> dict[str, Any]:
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")

    if request.town_id is None or request.growth_rate is None:
        raise HTTPException(status_code=400, detail="town_id and growth_rate required")

    result = await admin_client.send_gamescript(
        "set_town_growth", {"town_id": request.town_id, "days_between_growth": request.growth_rate}
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/deity/create_subsidy")
async def deity_create_subsidy(request: DeitySubsidyRequest) -> dict[str, Any]:
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")

    result = await admin_client.send_gamescript("create_subsidy", {
        "cargo_id": request.cargo_id,
        "src_type": request.src_type,
        "src_id": request.src_id,
        "dst_type": request.dst_type,
        "dst_id": request.dst_id,
    })
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})


@router.post("/deity/change_town_rating")
async def deity_change_town_rating(request: DeityTownRatingRequest) -> dict[str, Any]:
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")

    result = await admin_client.send_gamescript("change_town_rating", {
        "town_id": request.town_id,
        "company_id": request.company_id,
        "delta": request.delta,
    })
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result.get("result", {})
