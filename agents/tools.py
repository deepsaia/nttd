"""Agent-side query tools for nttd — example helper for agent authors.

These tools are NOT part of nttd.  They live in agent code and make HTTP/GS
calls to the running nttd server to fetch specific slices of game state.

All URLs are session-scoped: ``/sessions/{session_id}/...``.

Usage:
    from agents.tools import make_tools
    tools = make_tools(client, company_id=0)

    towns   = tools.get_towns()
    spots   = tools.find_bus_stop_spots(town_id=towns[0]["id"])
    engines = tools.get_engines(vehicle_type=1)

    # For LangChain:
    lc_tools = tools.as_langchain_tools()
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.nttd_client import NttdClient


class NttdTools:
    """Typed query tools scoped to one agent/company.

    Two categories:
      - Snapshot tools: read from nttd's cached WorldState (fast, no GS roundtrip).
      - GS tools: live round-trip to GameScript (for spatial candidates, engines, etc.).
    """

    def __init__(self, client: NttdClient, company_id: int) -> None:
        self._client = client
        self._company_id = company_id
        self._session_url = f"{client.base_url}/sessions/{client.session_id}"

    # ------------------------------------------------------------------
    # Snapshot tools  (reads nttd's cached WorldState via HTTP)
    # ------------------------------------------------------------------

    def get_towns(self) -> list[dict[str, Any]]:
        """All towns on the map. [{id, name, population, x, y, is_city}]"""
        import requests
        resp = requests.get(f"{self._session_url}/state/towns", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_industries(self) -> list[dict[str, Any]]:
        """All industries. [{id, name, type_name, x, y, is_raw, production}]"""
        import requests
        resp = requests.get(f"{self._session_url}/state/industries", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_vehicles(self, company_id: int | None = None) -> list[dict[str, Any]]:
        """Vehicles owned by this company. [{id, type, name, profit_this_year, in_depot, orders}]"""
        import requests
        resp = requests.get(f"{self._session_url}/state/vehicles", timeout=10)
        resp.raise_for_status()
        cid = company_id if company_id is not None else self._company_id
        return [v for v in resp.json() if v.get("company_id") == cid]

    def get_stations(self, company_id: int | None = None) -> list[dict[str, Any]]:
        """Stations owned by this company. [{id, name, x, y, has_bus, cargo_waiting}]"""
        import requests
        resp = requests.get(f"{self._session_url}/state/stations", timeout=10)
        resp.raise_for_status()
        cid = company_id if company_id is not None else self._company_id
        return [s for s in resp.json() if s.get("company_id") == cid]

    def get_compact(self) -> dict[str, Any]:
        """LLM-friendly summary for this company (~1-3 KB)."""
        return self._client.get_compact_snapshot()

    # ------------------------------------------------------------------
    # GS tools  (live round-trip to GameScript)
    # ------------------------------------------------------------------

    def get_companies(self) -> list[dict[str, Any]]:
        """All active companies. [{id, name, is_ai, color, manager}]"""
        return self._client.gs_query("get_companies").get("result", [])

    def get_company_finance(self, company_id: int | None = None) -> dict[str, Any]:
        """Financial details. {balance, loan, income, value, profit_last_year}"""
        cid = company_id if company_id is not None else self._company_id
        return self._client.gs_query("get_company_finance", {"company_id": cid}).get("result", {})

    def get_subsidies(self) -> list[dict[str, Any]]:
        """Active subsidies open to any company. [{cargo_label, src_name, dst_name, value}]"""
        return self._client.gs_query("get_subsidies").get("result", [])

    def get_engines(self, vehicle_type: int = 1, company_id: int | None = None) -> list[dict[str, Any]]:
        """Purchasable engines. vehicle_type: 0=train 1=road 2=ship 3=air."""
        cid = company_id if company_id is not None else self._company_id
        return self._client.gs_query("get_engines", {
            "company_id": cid, "vehicle_type": vehicle_type,
        }).get("result", [])

    def find_bus_stop_spots(self, town_id: int, max_results: int = 5) -> list[dict[str, Any]]:
        """Road tiles near town suitable for a bus/truck stop. [{tile, x, y}]"""
        return self._client.gs_query("find_bus_stop_spots", {
            "town_id": town_id,
            "company_id": self._company_id,
            "max_results": max_results,
        }).get("result", [])

    def find_depot_spots(self, town_id: int, max_results: int = 5) -> list[dict[str, Any]]:
        """Road tiles near town suitable for a road depot. [{tile, x, y}]"""
        return self._client.gs_query("find_depot_spots", {
            "town_id": town_id,
            "company_id": self._company_id,
            "max_results": max_results,
        }).get("result", [])

    def get_tile_info(self, tile: int) -> dict[str, Any]:
        """Terrain + infrastructure details for one map tile."""
        return self._client.gs_query("get_tile_info", {"tile": tile}).get("result", {})

    # ------------------------------------------------------------------
    # LangChain adapter — wrap each method as a @tool
    # ------------------------------------------------------------------

    def as_langchain_tools(self) -> list[Any]:
        """Return LangChain BaseTool instances wrapping each method."""
        from langchain_core.tools import tool  # type: ignore[import-untyped]

        _t = self

        @tool
        def get_towns() -> list[dict]:  # type: ignore[return]
            """List all towns with id, name, population, x, y."""
            return _t.get_towns()

        @tool
        def get_industries() -> list[dict]:  # type: ignore[return]
            """List all industries with type, location, and production info."""
            return _t.get_industries()

        @tool
        def get_vehicles() -> list[dict]:  # type: ignore[return]
            """List this company's vehicles: type, profit, depot status, orders."""
            return _t.get_vehicles()

        @tool
        def get_stations() -> list[dict]:  # type: ignore[return]
            """List this company's stations: name, location, cargo waiting."""
            return _t.get_stations()

        @tool
        def get_subsidies() -> list[dict]:  # type: ignore[return]
            """List active subsidies: cargo_label, src_name, dst_name, value."""
            return _t.get_subsidies()

        @tool
        def get_company_finance() -> dict:  # type: ignore[return]
            """This company's financials: balance, loan, income, value."""
            return _t.get_company_finance()

        @tool
        def get_engines(vehicle_type: int = 1) -> list[dict]:  # type: ignore[return]
            """Purchasable engine types. vehicle_type: 0=train 1=road 2=ship 3=air."""
            return _t.get_engines(vehicle_type=vehicle_type)

        @tool
        def find_bus_stop_spots(town_id: int, max_results: int = 5) -> list[dict]:  # type: ignore[return]
            """Find road tiles near a town suitable for bus/truck stops."""
            return _t.find_bus_stop_spots(town_id=town_id, max_results=max_results)

        @tool
        def find_depot_spots(town_id: int, max_results: int = 5) -> list[dict]:  # type: ignore[return]
            """Find road tiles near a town suitable for a road depot."""
            return _t.find_depot_spots(town_id=town_id, max_results=max_results)

        @tool
        def get_compact_snapshot() -> dict:  # type: ignore[return]
            """LLM-friendly compact state summary for this company."""
            return _t.get_compact()

        return [
            get_towns, get_industries, get_vehicles, get_stations,
            get_subsidies, get_company_finance, get_engines,
            find_bus_stop_spots, find_depot_spots, get_compact_snapshot,
        ]


def make_tools(client: NttdClient, company_id: int) -> NttdTools:
    """Convenience factory. Agents call this in __init__ or decide()."""
    return NttdTools(client, company_id)
