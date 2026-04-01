"""Repository for entity snapshot queries (towns, industries, stations, vehicles)."""

from typing import Any

from sqlalchemy import and_, func, select

from nttd.db.engine import get_session
from nttd.db.tables import (
    industries,
    industry_production,
    station_cargo,
    stations,
    subsidies,
    towns,
    vehicle_orders,
    vehicles,
)


async def get_towns_at(session_id: str, game_date: int) -> list[dict[str, Any]]:
    async with get_session() as db:
        rows = (
            await db.execute(
                select(towns).where(
                    and_(towns.c.session_id == session_id, towns.c.game_date == game_date)
                )
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_towns_latest(session_id: str) -> list[dict[str, Any]]:
    async with get_session() as db:
        subq = (
            select(func.max(towns.c.game_date).label("max_date"))
            .where(towns.c.session_id == session_id)
            .scalar_subquery()
        )
        rows = (
            await db.execute(
                select(towns).where(
                    and_(towns.c.session_id == session_id, towns.c.game_date == subq)
                )
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_town_history(
    session_id: str, town_id: int, from_date: int | None = None, to_date: int | None = None,
) -> list[dict[str, Any]]:
    async with get_session() as db:
        conditions = [towns.c.session_id == session_id, towns.c.town_id == town_id]
        if from_date is not None:
            conditions.append(towns.c.game_date >= from_date)
        if to_date is not None:
            conditions.append(towns.c.game_date <= to_date)
        rows = (
            await db.execute(select(towns).where(and_(*conditions)).order_by(towns.c.game_date))
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_industries_latest(session_id: str) -> list[dict[str, Any]]:
    async with get_session() as db:
        subq = (
            select(func.max(industries.c.game_date).label("max_date"))
            .where(industries.c.session_id == session_id)
            .scalar_subquery()
        )
        rows = (
            await db.execute(
                select(industries).where(
                    and_(industries.c.session_id == session_id, industries.c.game_date == subq)
                )
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_industry_production_latest(session_id: str) -> list[dict[str, Any]]:
    async with get_session() as db:
        subq = (
            select(func.max(industry_production.c.game_date).label("max_date"))
            .where(industry_production.c.session_id == session_id)
            .scalar_subquery()
        )
        rows = (
            await db.execute(
                select(industry_production).where(
                    and_(
                        industry_production.c.session_id == session_id,
                        industry_production.c.game_date == subq,
                    )
                )
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_stations_latest(session_id: str, company_id: int | None = None) -> list[dict[str, Any]]:
    async with get_session() as db:
        subq = (
            select(func.max(stations.c.game_date).label("max_date"))
            .where(stations.c.session_id == session_id)
            .scalar_subquery()
        )
        conditions = [stations.c.session_id == session_id, stations.c.game_date == subq]
        if company_id is not None:
            conditions.append(stations.c.company_id == company_id)
        rows = (await db.execute(select(stations).where(and_(*conditions)))).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_station_cargo_latest(session_id: str, station_id: int) -> list[dict[str, Any]]:
    async with get_session() as db:
        subq = (
            select(func.max(station_cargo.c.game_date).label("max_date"))
            .where(
                and_(
                    station_cargo.c.session_id == session_id,
                    station_cargo.c.station_id == station_id,
                )
            )
            .scalar_subquery()
        )
        rows = (
            await db.execute(
                select(station_cargo).where(
                    and_(
                        station_cargo.c.session_id == session_id,
                        station_cargo.c.station_id == station_id,
                        station_cargo.c.game_date == subq,
                    )
                )
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_vehicles_latest(session_id: str, company_id: int | None = None) -> list[dict[str, Any]]:
    async with get_session() as db:
        subq = (
            select(func.max(vehicles.c.game_date).label("max_date"))
            .where(vehicles.c.session_id == session_id)
            .scalar_subquery()
        )
        conditions = [vehicles.c.session_id == session_id, vehicles.c.game_date == subq]
        if company_id is not None:
            conditions.append(vehicles.c.company_id == company_id)
        rows = (await db.execute(select(vehicles).where(and_(*conditions)))).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_vehicle_orders_latest(session_id: str, vehicle_id: int) -> list[dict[str, Any]]:
    async with get_session() as db:
        subq = (
            select(func.max(vehicle_orders.c.game_date).label("max_date"))
            .where(
                and_(
                    vehicle_orders.c.session_id == session_id,
                    vehicle_orders.c.vehicle_id == vehicle_id,
                )
            )
            .scalar_subquery()
        )
        rows = (
            await db.execute(
                select(vehicle_orders).where(
                    and_(
                        vehicle_orders.c.session_id == session_id,
                        vehicle_orders.c.vehicle_id == vehicle_id,
                        vehicle_orders.c.game_date == subq,
                    )
                )
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_subsidies_latest(session_id: str) -> list[dict[str, Any]]:
    async with get_session() as db:
        subq = (
            select(func.max(subsidies.c.game_date).label("max_date"))
            .where(subsidies.c.session_id == session_id)
            .scalar_subquery()
        )
        rows = (
            await db.execute(
                select(subsidies).where(
                    and_(subsidies.c.session_id == session_id, subsidies.c.game_date == subq)
                )
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]
