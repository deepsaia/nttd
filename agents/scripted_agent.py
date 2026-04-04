"""Scripted demo agent — no LLM required.

Runs a simple rule-based strategy using NttdTools:
  Step 0:   Query towns, pick the two largest.
  Step 1:   Find bus-stop spots near each town, build stops + road depot.
  Step 2:   Buy a bus, set orders (town A → town B → repeat), start it.
  Step 3+:  Monitor profit; if any vehicle is idle in depot, send it out.

Supports two modes:
  - realtime (default): continuous observe→decide→act loop
  - heartbeat: wait for server trigger, then observe→decide→act

Usage:
  uv run python agents/scripted_agent.py --session-id ses_abc123 --company-id 0
  uv run python agents/scripted_agent.py --session-id ses_abc123 --mode heartbeat
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from agents.base import AgentBase, AgentContext, GameAction
from agents.tools import NttdTools, make_tools

logger = logging.getLogger("agent.scripted")


class ScriptedAgent(AgentBase):
    """Rule-based agent that builds a single bus route between the two largest towns.

    Tools are instantiated in __init__ and called directly — no LLM involved.
    Each decide() phase uses exactly the tools it needs and nothing more.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tools: NttdTools | None = None
        self._phase = "scout"
        self._town_a: dict[str, Any] | None = None
        self._town_b: dict[str, Any] | None = None
        self._stop_a: int | None = None
        self._stop_b: int | None = None
        self._depot_tile: int | None = None
        self._vehicle_id: int | None = None

    def _get_tools(self) -> NttdTools:
        """Lazily create the tool set once the client is connected."""
        if self._tools is None:
            self._tools = make_tools(self.client, self.company_id)
        return self._tools

    async def decide(self, context: AgentContext) -> list[GameAction]:
        tools = self._get_tools()

        if self._phase == "scout":
            return await self._phase_scout(tools)
        if self._phase == "build_stops":
            return await self._phase_build_stops(tools)
        if self._phase == "buy_vehicle":
            return await self._phase_buy_vehicle(tools)
        return self._phase_running(context)

    # ------------------------------------------------------------------
    # Phase: scout — find the two largest towns
    # ------------------------------------------------------------------

    async def _phase_scout(self, tools: NttdTools) -> list[GameAction]:
        self._agent_logger.info("phase=scout  querying towns...")
        towns = tools.get_towns()
        if not towns:
            self._agent_logger.info("No towns yet — waiting")
            return []

        towns_sorted = sorted(towns, key=lambda t: t.get("population", 0), reverse=True)
        self._town_a = towns_sorted[0]
        self._town_b = towns_sorted[1] if len(towns_sorted) > 1 else towns_sorted[0]
        self._agent_logger.info(
            "Picked towns: A=%s (pop %d)  B=%s (pop %d)",
            self._town_a["name"], self._town_a["population"],
            self._town_b["name"], self._town_b["population"],
        )
        self._phase = "build_stops"
        return []

    # ------------------------------------------------------------------
    # Phase: build stops + depot near town A and town B
    # ------------------------------------------------------------------

    async def _phase_build_stops(self, tools: NttdTools) -> list[GameAction]:
        actions: list[GameAction] = []

        if self._stop_a is None and self._town_a:
            candidates = tools.find_bus_stop_spots(town_id=self._town_a["id"], max_results=3)
            if candidates:
                tile = candidates[0]["tile"]
                self._stop_a = tile
                self._agent_logger.info(
                    "Building bus stop near %s at tile %d", self._town_a["name"], tile
                )
                actions.append(GameAction("build_road_stop", {
                    "company_id": self.company_id,
                    "tile": tile,
                    "length": 1,
                    "num_dirs": 1,
                    "is_truck": False,
                    "on_drive_through": False,
                }))
                if self._depot_tile is None:
                    depots = tools.find_depot_spots(town_id=self._town_a["id"], max_results=3)
                    if depots:
                        depot_tile = depots[0]["tile"]
                        self._depot_tile = depot_tile
                        self._agent_logger.info("Building road depot at tile %d", depot_tile)
                        actions.append(GameAction("build_road_depot", {
                            "company_id": self.company_id,
                            "tile": depot_tile,
                        }))
            else:
                self._agent_logger.warning("No bus stop spots found near %s", self._town_a["name"])

        if self._stop_b is None and self._town_b and self._stop_a is not None:
            candidates = tools.find_bus_stop_spots(town_id=self._town_b["id"], max_results=3)
            if candidates:
                tile = candidates[0]["tile"]
                self._stop_b = tile
                self._agent_logger.info(
                    "Building bus stop near %s at tile %d", self._town_b["name"], tile
                )
                actions.append(GameAction("build_road_stop", {
                    "company_id": self.company_id,
                    "tile": tile,
                    "length": 1,
                    "num_dirs": 1,
                    "is_truck": False,
                    "on_drive_through": False,
                }))

        if self._stop_a is not None and self._stop_b is not None and self._depot_tile is not None:
            self._agent_logger.info(
                "Stops built: A=%d  B=%d  depot=%d -> advancing to buy_vehicle",
                self._stop_a, self._stop_b, self._depot_tile,
            )
            self._phase = "buy_vehicle"

        return actions

    # ------------------------------------------------------------------
    # Phase: buy a bus and assign the route
    # ------------------------------------------------------------------

    async def _phase_buy_vehicle(self, tools: NttdTools) -> list[GameAction]:
        engine_list = tools.get_engines(vehicle_type=1)
        bus_engines = [e for e in engine_list if e.get("cargo_label") in ("PASS", "PASSENGERS", "")]
        if not bus_engines:
            bus_engines = engine_list

        if not bus_engines:
            self._agent_logger.warning("No road vehicle engines available yet — waiting")
            return []

        engine_id = bus_engines[0]["id"]
        self._agent_logger.info(
            "Buying vehicle: engine_id=%d  depot=%d", engine_id, self._depot_tile
        )
        actions: list[GameAction] = [GameAction("buy_vehicle", {
            "company_id": self.company_id,
            "depot_tile": self._depot_tile,
            "engine_id": engine_id,
        })]

        vlist = tools.get_vehicles()
        if vlist:
            self._vehicle_id = vlist[-1]["id"]
            self._agent_logger.info("Vehicle created: id=%d", self._vehicle_id)

            if self._vehicle_id is not None:
                actions.append(GameAction("add_order", {
                    "company_id": self.company_id,
                    "vehicle_id": self._vehicle_id,
                    "order_index": 0,
                    "destination": self._stop_a,
                }))
                actions.append(GameAction("add_order", {
                    "company_id": self.company_id,
                    "vehicle_id": self._vehicle_id,
                    "order_index": 1,
                    "destination": self._stop_b,
                }))
                actions.append(GameAction("start_vehicle", {
                    "company_id": self.company_id,
                    "vehicle_id": self._vehicle_id,
                }))
                self._phase = "running"
                self._agent_logger.info(
                    "Route set: vehicle %d  %d <-> %d  -> phase=running",
                    self._vehicle_id, self._stop_a, self._stop_b,
                )

        return actions

    # ------------------------------------------------------------------
    # Phase: running — log stats each cycle, rescue stuck vehicles
    # ------------------------------------------------------------------

    def _phase_running(self, context: AgentContext) -> list[GameAction]:
        actions: list[GameAction] = []
        vehicles = context.compact.get("vehicles", {})
        in_depot = vehicles.get("in_depot", 0)
        total = vehicles.get("total", 0)

        self._agent_logger.info(
            "phase=running  vehicles=%d  in_depot=%d  profit_this_year=%s",
            total, in_depot,
            f"{vehicles.get('avg_profit_this_year', 0):,}",
        )

        if in_depot > 0 and self._vehicle_id is not None:
            self._agent_logger.info("Vehicle %d stuck in depot — restarting", self._vehicle_id)
            actions.append(GameAction("start_vehicle", {
                "company_id": self.company_id,
                "vehicle_id": self._vehicle_id,
            }))

        return actions


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Scripted demo agent for nttd")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--session-id", required=True, help="nttd session ID (e.g. ses_abc123)")
    parser.add_argument("--company-id", type=int, default=0)
    parser.add_argument("--agent-id", default=None)
    parser.add_argument("--mode", choices=["realtime", "heartbeat"], default="realtime",
                        help="Runtime mode (default: realtime)")
    parser.add_argument("--poll-interval", type=float, default=2.0,
                        help="Seconds between observe cycles in realtime mode (default: 2.0)")
    args = parser.parse_args()

    agent = ScriptedAgent(
        base_url=args.base_url,
        session_id=args.session_id,
        company_id=args.company_id,
        agent_id=args.agent_id,
    )

    if args.mode == "realtime":
        asyncio.run(agent.run_realtime(poll_interval=args.poll_interval))
    else:
        asyncio.run(agent.run())


if __name__ == "__main__":
    main()
