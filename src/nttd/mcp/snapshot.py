"""Reshape game replies before an agent reads them.

Three changes, each with its own reason:

- A company's ``income`` holds the revenue of the last completed game quarter and is
  refreshed only when a quarter ends, so it is renamed ``revenue_last_quarter``.
- A vehicle's numeric ``state`` becomes the word the game uses for a single-vehicle
  query. Three fields are dropped: ``idle_reason`` is always empty in the fleet
  list, ``lost`` is never set because the game script never receives that event,
  and ``running`` repeats the state code and reads true for a vehicle at speed zero.
- A command error that reports a search timeout gets a note saying what it means.
"""

from __future__ import annotations

from typing import Any

TIMEOUT_NOTE = (
    "The game searched for a route until its 120 s limit and found none. "
    "A search between two points with no possible route runs to the limit."
)


DROPPED_VEHICLE_FIELDS = ("idle_reason", "lost", "running")
STATE_WORDS = {1: "stopped", 2: "in_depot", 3: "at_station", 4: "broken_down", 5: "crashed"}


def rename_income(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the snapshot with each company's "income" named "revenue_last_quarter"."""
    companies = snapshot.get("companies")
    if not isinstance(companies, list):
        return snapshot
    return {
        **snapshot,
        "companies": [
            {
                ("revenue_last_quarter" if key == "income" else key): value
                for key, value in company.items()
            }
            if isinstance(company, dict)
            else company
            for company in companies
        ],
    }


def vehicle_state_of(vehicle: dict[str, Any], without_path: set[Any]) -> str:
    """The vehicle's state as a word.

    A running vehicle at speed zero reads "halted". A vehicle the route check found
    cut off from its stations reads "no_path", moving or not.
    """
    if vehicle.get("id") in without_path:
        return "no_path"
    word = STATE_WORDS.get(vehicle.get("state"))
    if word is not None:
        return word
    return "running" if (vehicle.get("current_speed") or 0) > 0 else "halted"


def with_vehicle_state_words(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the snapshot with each vehicle's state as a word and three fields dropped."""
    vehicles = snapshot.get("vehicles")
    if not isinstance(vehicles, list):
        return snapshot
    without_path = {
        vid
        for route in snapshot.get("routes") or []
        if isinstance(route, dict)
        for vid in route.get("vehicles_without_path") or []
    }
    return {
        **snapshot,
        "vehicles": [
            {
                **{key: value for key, value in vehicle.items() if key not in DROPPED_VEHICLE_FIELDS},
                "state": vehicle_state_of(vehicle, without_path),
            }
            if isinstance(vehicle, dict)
            else vehicle
            for vehicle in vehicles
        ],
    }


def reshape(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Apply every snapshot change in one call."""
    return with_vehicle_state_words(rename_income(snapshot))


def explain_timeouts(action_results: list[Any]) -> list[Any]:
    """Add what a search timeout means to each result that reports one."""
    explained = []
    for result in action_results:
        error = result.get("error") if isinstance(result, dict) else None
        if isinstance(error, str) and "did not answer within" in error:
            result = {**result, "error": f"{error}. {TIMEOUT_NOTE}"}
        explained.append(result)
    return explained


def reshape_query(name: str, reply: dict[str, Any]) -> dict[str, Any]:
    """Use the same state words in vehicle queries and observations; retain details."""
    if not reply.get("success") or name not in {"get_vehicle_info", "get_vehicles"}:
        return reply
    payload = reply.get("result")
    def vehicle(value: Any) -> Any:
        if not isinstance(value, dict) or "state" not in value:
            return value
        return {**value, "state": vehicle_state_of(value, set())}
    result = [vehicle(item) for item in payload] if isinstance(payload, list) else vehicle(payload)
    return {**reply, "result": result}
