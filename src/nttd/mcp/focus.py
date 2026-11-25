"""Per-agent map focus.

An agent sets a focus: a tile rectangle around towns and industries it names, or
given directly. The server then cuts every snapshot that agent receives to the
rectangle and adds an index of the places outside it. Agents without a focus
keep receiving the whole map.
"""

from __future__ import annotations

import json
from typing import Any

DEFAULT_PADDING = 8
INDEXED_KINDS = ("towns", "industries")
SINGULAR = {"towns": "town", "industries": "industry"}
POSITIONED_KINDS = ("towns", "industries", "stations")
CORNERS = ("x1", "y1", "x2", "y2")


def coerce_names(value: Any) -> list[str]:
    """Read names or ids that may arrive as a list, a scalar, or a JSON string."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                return [text]
        else:
            return [part.strip() for part in text.split(",") if part.strip()]
    if not isinstance(value, list):
        value = [value]
    return [str(item).strip() for item in value if str(item).strip()]


def coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def find_entity(entities: list[dict], label: str) -> dict | None:
    """Match a town or industry by id, or by name without regard to case."""
    if label.isdigit():
        wanted = int(label)
        for entity in entities:
            if entity.get("id") == wanted:
                return entity
    folded = label.casefold()
    for entity in entities:
        if str(entity.get("name", "")).casefold() == folded:
            return entity
    return None


def map_size(snapshot: dict) -> tuple[int, int]:
    game = snapshot.get("game") or {}
    return int(game.get("map_width") or 0), int(game.get("map_height") or 0)


def tile_xy(tile: int, width: int) -> tuple[int, int]:
    return tile % width, tile // width


def inside(rect: dict, x: Any, y: Any) -> bool:
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return False
    return rect["x1"] <= x <= rect["x2"] and rect["y1"] <= y <= rect["y2"]


def clamp_rect(rect: dict, size: tuple[int, int]) -> dict:
    width, height = size
    x1, x2 = sorted((rect["x1"], rect["x2"]))
    y1, y2 = sorted((rect["y1"], rect["y2"]))
    x1, y1 = max(0, x1), max(0, y1)
    if width:
        x2 = min(width - 1, x2)
    if height:
        y2 = min(height - 1, y2)
    return {"x1": x1, "y1": y1, "x2": max(x1, x2), "y2": max(y1, y2)}


def rect_around(
    points: list[tuple[int, int]], padding: int, size: tuple[int, int]
) -> dict:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    rect = {
        "x1": min(xs) - padding,
        "y1": min(ys) - padding,
        "x2": max(xs) + padding,
        "y2": max(ys) + padding,
    }
    return clamp_rect(rect, size)


def union_rect(first: dict, second: dict) -> dict:
    return {
        "x1": min(first["x1"], second["x1"]),
        "y1": min(first["y1"], second["y1"]),
        "x2": max(first["x2"], second["x2"]),
        "y2": max(first["y2"], second["y2"]),
    }


def rects_overlap(first: dict, second: dict) -> bool:
    return (
        first["x1"] <= second["x2"]
        and second["x1"] <= first["x2"]
        and first["y1"] <= second["y2"]
        and second["y1"] <= first["y2"]
    )


def vehicle_inside(vehicle: dict, rect: dict, width: int) -> bool:
    """A vehicle counts as inside when it is there or has an order to a station there."""
    if inside(rect, vehicle.get("x"), vehicle.get("y")):
        return True
    if not width:
        return False
    for order in vehicle.get("orders") or []:
        tile = order.get("destination")
        if isinstance(tile, int) and inside(rect, *tile_xy(tile, width)):
            return True
    return False


def clip_snapshot(snapshot: dict, rect: dict) -> tuple[dict, dict]:
    """Cut the entity lists to the rectangle. Returns the clipped snapshot and
    the count of entities left out, per kind."""
    width, _ = map_size(snapshot)
    clipped = dict(snapshot)
    hidden = {}
    for kind in POSITIONED_KINDS:
        items = snapshot.get(kind) or []
        kept = [
            entity for entity in items if inside(rect, entity.get("x"), entity.get("y"))
        ]
        clipped[kind] = kept
        hidden[kind] = len(items) - len(kept)
    vehicles = snapshot.get("vehicles") or []
    kept_vehicles = [
        vehicle for vehicle in vehicles if vehicle_inside(vehicle, rect, width)
    ]
    clipped["vehicles"] = kept_vehicles
    hidden["vehicles"] = len(vehicles) - len(kept_vehicles)
    station_ids = {station.get("id") for station in clipped["stations"]}
    vehicle_ids = {vehicle.get("id") for vehicle in kept_vehicles}
    routes = snapshot.get("routes") or []
    kept_routes = [
        route
        for route in routes
        if station_ids.intersection(route.get("station_ids") or [])
        or vehicle_ids.intersection(route.get("vehicle_ids") or [])
    ]
    clipped["routes"] = kept_routes
    hidden["routes"] = len(routes) - len(kept_routes)
    return clipped, hidden


def index_outside(snapshot: dict, rect: dict) -> list[dict]:
    """Towns and industries outside the rectangle, with their coordinates."""
    index = []
    for kind in INDEXED_KINDS:
        for entity in snapshot.get(kind) or []:
            x, y = entity.get("x"), entity.get("y")
            if inside(rect, x, y):
                continue
            entry = {
                "kind": SINGULAR[kind],
                "id": entity.get("id"),
                "name": entity.get("name"),
                "x": x,
                "y": y,
            }
            if kind == "industries":
                entry["type"] = entity.get("type_name")
            index.append(entry)
    return index


class FocusRegistry:
    """One focus rectangle per agent tag, and the views cut through them."""

    def __init__(self) -> None:
        self.focuses: dict[str, dict] = {}

    def get(self, tag: str) -> dict | None:
        return self.focuses.get(tag)

    def clear(self, tag: str) -> None:
        self.focuses.pop(tag, None)

    def set_focus(self, tag: str, snapshot: dict, args: dict) -> dict:
        """Resolve the requested places and store the rectangle. Returns the
        stored focus, or an error when a place is unknown or nothing was given."""
        size = map_size(snapshot)
        padding = coerce_int(args.get("padding"))
        padding = DEFAULT_PADDING if padding is None else max(0, padding)
        points, anchors, unknown = [], [], []
        for kind in INDEXED_KINDS:
            for label in coerce_names(args.get(kind)):
                entity = find_entity(snapshot.get(kind) or [], label)
                if entity is None:
                    unknown.append(label)
                    continue
                points.append((entity["x"], entity["y"]))
                anchors.append(
                    {
                        "kind": SINGULAR[kind],
                        "id": entity.get("id"),
                        "name": entity.get("name"),
                    }
                )
        if unknown:
            return {"error": "Unknown town or industry: " + ", ".join(unknown)}
        corners = [coerce_int(args.get(key)) for key in CORNERS]
        rect = (
            clamp_rect(dict(zip(CORNERS, corners)), size)
            if all(c is not None for c in corners)
            else None
        )
        if points:
            around = rect_around(points, padding, size)
            rect = union_rect(rect, around) if rect else around
        if rect is None:
            return {"error": "Give towns, industries, or a rectangle x1, y1, x2, y2."}
        self.focuses[tag] = {**rect, "padding": padding, "anchors": anchors}
        return {"focus": self.focuses[tag]}

    def apply(self, tag: str, result: dict) -> dict:
        """Return the result cut to the agent's focus. Results without a
        snapshot, and agents without a focus, pass through unchanged."""
        focus = self.focuses.get(tag)
        if focus is None:
            return result
        if isinstance(result.get("snapshot"), dict):
            clipped, hidden = clip_snapshot(result["snapshot"], focus)
            return {
                **result,
                "snapshot": clipped,
                **self.view_fields(tag, result["snapshot"], hidden),
            }
        if any(kind in result for kind in POSITIONED_KINDS):
            clipped, hidden = clip_snapshot(result, focus)
            return {**clipped, **self.view_fields(tag, result, hidden)}
        return result

    def view_fields(self, tag: str, snapshot: dict, hidden: dict) -> dict:
        focus = self.focuses[tag]
        overlapping = sorted(
            other
            for other, rect in self.focuses.items()
            if other != tag and rects_overlap(rect, focus)
        )
        return {
            "focus": {**focus, "overlapping": overlapping},
            "outside": {"places": index_outside(snapshot, focus), "counts": hidden},
        }
