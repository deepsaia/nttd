"""Reshape game replies before an agent reads them.

Three changes, each with its own reason:

- A company's ``income`` holds the revenue of the last completed game quarter and is
  refreshed only when a quarter ends, so it is renamed ``revenue_last_quarter``.
- A vehicle's numeric ``state`` becomes the word the game uses for a single-vehicle
  query. Route reachability is reported separately, so a path problem cannot hide
  a stopped or crashed vehicle. Redundant or unreliable legacy flags are dropped.
- A command error that reports a search timeout gets a note saying what it means.
"""

from __future__ import annotations

from typing import Any

TIMEOUT_NOTE = (
    "The command did not return before the response deadline. "
    "This does not prove that a route is impossible or that the command made no changes."
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


def vehicle_state_of(vehicle: dict[str, Any]) -> str:
    """The vehicle's state as a word.

    A running vehicle at speed zero reads "halted". Reachability is a separate fact;
    it must not hide whether the vehicle is stopped, broken down or crashed.
    """
    word = STATE_WORDS.get(vehicle.get("state"))
    if word is not None:
        return word
    if vehicle.get("state") in {*STATE_WORDS.values(), "running", "halted", "unknown"}:
        return vehicle["state"]
    if vehicle.get("state") != 0:
        return "unknown"
    return "running" if (vehicle.get("current_speed") or 0) > 0 else "halted"


def with_vehicle_state_words(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the snapshot with each vehicle's state as a word and three fields dropped."""
    vehicles = snapshot.get("vehicles")
    if not isinstance(vehicles, list):
        return snapshot
    reachability = {}
    for route in snapshot.get("routes") or []:
        if not isinstance(route, dict):
            continue
        for vid in route.get("vehicle_ids") or []:
            if (vid in (route.get("vehicles_without_path") or [])
                    or (route.get("connection_checked_at") and not route.get("track_confirmed_at"))):
                reachability[vid] = "no_path"
            elif vid in (route.get("vehicles_with_unknown_path") or []):
                reachability[vid] = "unknown"
            elif route.get("track_confirmed_at") or route.get("status") == "active":
                reachability[vid] = "connected"
            elif route.get("connection_checked_at"):
                reachability[vid] = "no_path"
            else:
                reachability[vid] = "unknown"
        for vid in route.get("vehicles_without_path") or []:
            reachability[vid] = "no_path"
    return {
        **snapshot,
        "vehicles": [
            {
                **{key: value for key, value in vehicle.items() if key not in DROPPED_VEHICLE_FIELDS},
                "state": vehicle_state_of(vehicle),
                "route_reachability": reachability.get(vehicle.get("id"), "unknown"),
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


def _reshape_vehicle_query(value: Any) -> Any:
    """Use the observation state words without discarding query details."""
    if not isinstance(value, dict) or "state" not in value:
        return value
    return {**value, "state": vehicle_state_of(value), "route_reachability": "unknown"}


def reshape_query(name: str, reply: dict[str, Any]) -> dict[str, Any]:
    """Use the same state words in vehicle queries and observations; retain details."""
    if not reply.get("success") or name not in {"get_vehicle_info", "get_vehicles"}:
        return reply
    payload = reply.get("result")
    result = ([_reshape_vehicle_query(item) for item in payload]
              if isinstance(payload, list) else _reshape_vehicle_query(payload))
    return {**reply, "result": result}
