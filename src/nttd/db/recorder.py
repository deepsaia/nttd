"""Session recorder: ingests game data and writes to DB via background flush.

All record_* methods append to in-memory buffers (non-blocking).
A background task flushes buffers to DB in batched transactions.

Ref: docs/openttd_study_part4_multiplayer_agent_design.md §13, §17
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert

from nttd.db import tables
from nttd.db.engine import get_session
from nttd.db.parquet_writer import ParquetWriter
from nttd.schemas.action_envelope import ActionEnvelope
from nttd.schemas.action_result import ActionResult
from nttd.schemas.snapshot import StateSnapshot

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL_SECONDS: float = 1.0
_MAX_BUFFER_SIZE: int = 5000


class SessionRecorder:

    def __init__(
        self, session_id: str, flush_interval: float = _FLUSH_INTERVAL_SECONDS,
        data_dir: str = "data/sessions",
    ):
        self.session_id: str = session_id
        self._flush_interval: float = flush_interval
        self._buffers: dict[str, list[dict[str, Any]]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        self._running: bool = False
        self._snapshot_count: int = 0
        self._total_rows_flushed: int = 0
        self._flush_count: int = 0
        self._parquet: ParquetWriter = ParquetWriter(session_id, data_dir)

    async def start(self) -> None:
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("SessionRecorder started for session %s", self.session_id)

    async def stop(self) -> None:
        self._running = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush_once()
        self._parquet.flush()
        logger.info(
            "SessionRecorder stopped: %d snapshots (%d parquet), %d rows flushed in %d batches",
            self._snapshot_count,
            self._parquet.total_written,
            self._total_rows_flushed,
            self._flush_count,
        )

    def _append(self, table_name: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        buf = self._buffers.setdefault(table_name, [])
        buf.extend(rows)

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._flush_interval)
            try:
                await self._flush_once()
            except Exception:
                logger.exception("Flush failed")

    async def _flush_once(self) -> None:
        async with self._lock:
            if not self._buffers:
                return
            buffers_to_flush = self._buffers
            self._buffers = {}

        total_rows = 0
        t0 = time.monotonic()

        table_map = {
            "snapshots": tables.snapshots,
            "companies": tables.companies,
            "finances": tables.finances,
            "finance_revenue": tables.finance_revenue,
            "finance_expenses": tables.finance_expenses,
            "finance_quarterly": tables.finance_quarterly,
            "infrastructure": tables.infrastructure,
            "towns": tables.towns,
            "industries": tables.industries,
            "industry_production": tables.industry_production,
            "stations": tables.stations,
            "station_cargo": tables.station_cargo,
            "vehicles": tables.vehicles,
            "vehicle_orders": tables.vehicle_orders,
            "subsidies": tables.subsidies,
            "cargo_flows": tables.cargo_flows,
            "actions": tables.actions,
            "action_parameters": tables.action_parameters,
            "events": tables.events,
            "messages": tables.messages,
            "metrics": tables.metrics,
        }

        async with get_session() as db:
            async with db.begin():
                for table_name, rows in buffers_to_flush.items():
                    table = table_map.get(table_name)
                    if table is None:
                        logger.warning("Unknown table in buffer: %s", table_name)
                        continue
                    if rows:
                        await db.execute(insert(table), rows)
                        total_rows += len(rows)

        elapsed_ms = (time.monotonic() - t0) * 1000
        self._total_rows_flushed += total_rows
        self._flush_count += 1
        if total_rows > 0:
            logger.debug("Flushed %d rows across %d tables in %.1fms", total_rows, len(buffers_to_flush), elapsed_ms)

    # ------------------------------------------------------------------
    # Snapshot recording (non-blocking: appends to buffers)
    # ------------------------------------------------------------------

    def record_snapshot(self, snapshot: StateSnapshot) -> None:
        game_date = snapshot.game.game_date
        sid = self.session_id
        self._snapshot_count += 1

        # Snapshot metadata to DB; full state to Parquet for replay
        self._append("snapshots", [
            {
                "session_id": sid,
                "snapshot_id": snapshot.game.snapshot_id,
                "game_date": game_date,
                "tick": snapshot.game.tick,
            }
        ])
        self._parquet.append(snapshot)

        self._record_companies(sid, game_date, snapshot)
        self._record_finances(sid, game_date, snapshot)
        self._record_towns(sid, game_date, snapshot)
        self._record_industries(sid, game_date, snapshot)
        self._record_stations(sid, game_date, snapshot)
        self._record_vehicles(sid, game_date, snapshot)
        self._record_subsidies(sid, game_date, snapshot)
        self._record_metrics(sid, game_date, snapshot)

        buf_size = sum(len(v) for v in self._buffers.values())
        if buf_size >= _MAX_BUFFER_SIZE:
            asyncio.create_task(self._flush_once())

    def _record_companies(self, sid: str, game_date: int, snapshot: StateSnapshot) -> None:
        self._append("companies", [
            {
                "session_id": sid,
                "game_date": game_date,
                "company_id": c.id,
                "name": c.name,
                "manager": c.manager,
                "color": c.color,
                "is_ai": c.is_ai,
                "is_active": c.is_active,
            }
            for c in snapshot.companies
        ])

    def _record_finances(self, sid: str, game_date: int, snapshot: StateSnapshot) -> None:
        self._append("finances", [
            {
                "session_id": sid,
                "game_date": game_date,
                "company_id": c.id,
                "balance": c.money,
                "loan": c.loan,
                "max_loan": 0,
                "income": c.income,
                "expenses": 0,
                "company_value": c.value,
                "performance_rating": 0,
                "cargo_delivered": 0,
            }
            for c in snapshot.companies
        ])

    def _record_towns(self, sid: str, game_date: int, snapshot: StateSnapshot) -> None:
        self._append("towns", [
            {
                "session_id": sid,
                "game_date": game_date,
                "town_id": t.id,
                "name": t.name,
                "population": t.population,
                "houses": t.houses,
                "x": t.x,
                "y": t.y,
                "is_city": t.is_city,
                "growth_rate": t.growth_rate,
            }
            for t in snapshot.towns
        ])

    def _record_industries(self, sid: str, game_date: int, snapshot: StateSnapshot) -> None:
        ind_rows = []
        prod_rows = []
        for ind in snapshot.industries:
            ind_rows.append({
                "session_id": sid,
                "game_date": game_date,
                "industry_id": ind.id,
                "name": ind.name,
                "type_id": ind.type_id,
                "type_name": ind.type_name,
                "x": ind.x,
                "y": ind.y,
                "is_raw": ind.is_raw,
                "is_processing": ind.is_processing,
            })
            for p in ind.production:
                prod_rows.append({
                    "session_id": sid,
                    "game_date": game_date,
                    "industry_id": ind.id,
                    "cargo_id": p.cargo_id,
                    "cargo_label": p.cargo_label,
                    "produced": p.last_month,
                    "transported_pct": p.transported,
                })
        self._append("industries", ind_rows)
        self._append("industry_production", prod_rows)

    def _record_stations(self, sid: str, game_date: int, snapshot: StateSnapshot) -> None:
        stn_rows = []
        cargo_rows = []
        for s in snapshot.stations:
            stn_rows.append({
                "session_id": sid,
                "game_date": game_date,
                "station_id": s.id,
                "company_id": s.company_id,
                "name": s.name,
                "x": s.x,
                "y": s.y,
                "has_rail": s.has_rail,
                "has_truck": s.has_truck,
                "has_bus": s.has_bus,
                "has_airport": s.has_airport,
                "has_dock": s.has_dock,
            })
            for cw in s.cargo_waiting:
                cargo_rows.append({
                    "session_id": sid,
                    "game_date": game_date,
                    "station_id": s.id,
                    "cargo_id": cw.cargo_id,
                    "cargo_label": cw.cargo_label,
                    "waiting": cw.waiting,
                    "rating": None,
                })
        self._append("stations", stn_rows)
        self._append("station_cargo", cargo_rows)

    def _record_vehicles(self, sid: str, game_date: int, snapshot: StateSnapshot) -> None:
        veh_rows = []
        order_rows = []
        for v in snapshot.vehicles:
            veh_rows.append({
                "session_id": sid,
                "game_date": game_date,
                "vehicle_id": v.id,
                "company_id": v.company_id,
                "vehicle_type": v.type,
                "name": v.name,
                "engine_id": v.engine_id,
                "x": v.x,
                "y": v.y,
                "profit_this_year": v.profit_this_year,
                "profit_last_year": v.profit_last_year,
                "age": v.age,
                "max_age": v.max_age,
                "current_speed": v.current_speed,
                "state": v.state,
                "running": v.running,
                "in_depot": v.in_depot,
            })
            for o in v.orders:
                if o.is_goto_station:
                    order_type = "station"
                elif o.is_goto_depot:
                    order_type = "depot"
                elif o.is_goto_waypoint:
                    order_type = "waypoint"
                else:
                    order_type = "unknown"
                order_rows.append({
                    "session_id": sid,
                    "game_date": game_date,
                    "vehicle_id": v.id,
                    "order_index": o.index,
                    "destination_id": o.destination,
                    "order_type": order_type,
                    "flags": o.flags,
                })
        self._append("vehicles", veh_rows)
        self._append("vehicle_orders", order_rows)

    def _record_subsidies(self, sid: str, game_date: int, snapshot: StateSnapshot) -> None:
        self._append("subsidies", [
            {
                "session_id": sid,
                "game_date": game_date,
                "subsidy_id": s.id,
                "cargo_id": s.cargo_id,
                "cargo_label": s.cargo_label,
                "src_type": s.src_type,
                "src_id": s.src_id,
                "src_name": s.src_name,
                "dst_type": s.dst_type,
                "dst_id": s.dst_id,
                "dst_name": s.dst_name,
                "value": s.value,
                "remaining_years": s.remaining_years,
            }
            for s in snapshot.subsidies
        ])

    def _record_metrics(self, sid: str, game_date: int, snapshot: StateSnapshot) -> None:
        rows: list[dict[str, Any]] = []
        base = {"session_id": sid, "game_date": game_date}
        for c in snapshot.companies:
            cb = {**base, "company_id": c.id}
            rows.extend([
                {**cb, "metric_name": "balance", "metric_value": float(c.money)},
                {**cb, "metric_name": "loan", "metric_value": float(c.loan)},
                {**cb, "metric_name": "income", "metric_value": float(c.income)},
                {**cb, "metric_name": "company_value", "metric_value": float(c.value)},
                {**cb, "metric_name": "profit_last_year", "metric_value": float(c.profit_last_year)},
            ])

        vehicle_counts: dict[tuple[int, str], int] = {}
        for v in snapshot.vehicles:
            key = (v.company_id, v.type)
            vehicle_counts[key] = vehicle_counts.get(key, 0) + 1
        for (cid, vtype), count in vehicle_counts.items():
            rows.append({
                **base, "company_id": cid,
                "metric_name": f"vehicles_{vtype}", "metric_value": float(count),
            })

        station_counts: dict[int, int] = {}
        for s in snapshot.stations:
            station_counts[s.company_id] = station_counts.get(s.company_id, 0) + 1
        for cid, count in station_counts.items():
            rows.append({
                **base, "company_id": cid,
                "metric_name": "stations", "metric_value": float(count),
            })

        total_pop = sum(t.population for t in snapshot.towns)
        rows.append({
            **base, "company_id": None,
            "metric_name": "total_population", "metric_value": float(total_pop),
        })

        self._append("metrics", rows)

    # ------------------------------------------------------------------
    # Action recording (non-blocking)
    # ------------------------------------------------------------------

    def record_action(self, envelope: ActionEnvelope, result: ActionResult) -> None:
        self._append("actions", [
            {
                "session_id": self.session_id,
                "action_id": envelope.action_id,
                "participant_id": envelope.metadata.get("participant_id"),
                "participant_type": envelope.metadata.get("participant_type"),
                "company_id": envelope.company_id,
                "game_date": envelope.metadata.get("game_date"),
                "action_type": envelope.action_type,
                "action_mode": envelope.mode,
                "status": result.status,
                "error": result.error if result.error else None,
                "cost": envelope.metadata.get("cost"),
                "submitted_at": envelope.metadata.get("submitted_at"),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        ])

        param_rows = [
            {"action_id": envelope.action_id, "param_key": k, "param_value": str(v)}
            for k, v in envelope.parameters.items()
        ]
        self._append("action_parameters", param_rows)

    # ------------------------------------------------------------------
    # Event recording (non-blocking)
    # ------------------------------------------------------------------

    def record_event(
        self,
        game_date: int,
        event_type: str,
        company_id: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        detail: str | None = None,
    ) -> None:
        self._append("events", [
            {
                "session_id": self.session_id,
                "game_date": game_date,
                "event_type": event_type,
                "company_id": company_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "detail": detail,
            }
        ])

    # ------------------------------------------------------------------
    # Message recording (non-blocking)
    # ------------------------------------------------------------------

    def record_message(
        self,
        message_id: str,
        game_date: int | None,
        message_type: str,
        from_id: str | None = None,
        to_id: str | None = None,
        company_id: int | None = None,
        body: str | None = None,
    ) -> None:
        self._append("messages", [
            {
                "session_id": self.session_id,
                "message_id": message_id,
                "game_date": game_date,
                "message_type": message_type,
                "from_id": from_id,
                "to_id": to_id,
                "company_id": company_id,
                "body": body,
            }
        ])
