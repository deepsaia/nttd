from typing import Any

from fastapi import APIRouter, HTTPException

from nttd.api.dependencies import admin_client, world
from nttd.schemas.company import Company
from nttd.schemas.industry import Industry
from nttd.schemas.snapshot import StateSnapshot
from nttd.schemas.station import Station
from nttd.schemas.town import Town
from nttd.schemas.vehicle import Vehicle

router = APIRouter(prefix="/state", tags=["observation"])


@router.get("/full", response_model=StateSnapshot)
def get_full_state() -> StateSnapshot:
    return world.snapshot()


@router.get("/company/{company_id}", response_model=Company)
def get_company(company_id: int) -> Company:
    company = world.companies.get(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"Company {company_id} not found")
    return company


@router.get("/towns", response_model=list[Town])
def get_towns() -> list[Town]:
    return list(world.towns.values())


@router.get("/industries", response_model=list[Industry])
def get_industries() -> list[Industry]:
    return list(world.industries.values())


@router.get("/stations", response_model=list[Station])
def get_stations() -> list[Station]:
    return list(world.stations.values())


@router.get("/vehicles", response_model=list[Vehicle])
def get_vehicles() -> list[Vehicle]:
    return list(world.vehicles.values())


@router.post("/gs/query")
async def gs_query(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Query game state via GameScript. Requires OpenTTD connection and nttd-gs loaded."""
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    return await admin_client.send_gamescript(action, params)
