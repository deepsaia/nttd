"""Which tiles an action may have changed.

Arithmetic over the action's own parameters and over what it reported building. It is a
separate, pure function because it is the part worth testing: getting it wrong means a
stored map that quietly disagrees with the game, and a map that is quietly wrong is worse
than no map, since everything reading it believes it.

Deliberately generous. Re-reading a tile that did not change costs one cheap query;
missing one that did leaves a stored map claiming ground is empty when a station stands on
it, and every route planned over it is planned over a fiction.
"""

from __future__ import annotations

from typing import Any

from nttd.constants import KNOWN_ACTIONS

# Tiles of slack around whatever the action named.
#
# A build is not confined to the tile it is given. A rail station with three platforms
# covers three tiles from its corner, an airport covers a rectangle, a depot alters the
# tile in front of it, and a road or rail join touches everything between its ends. Rather
# than model each footprint, which would be one more copy of the game's own rules to keep
# in step, the area is padded and re-read.
_PAD = 4

# Actions that change the shape of the land itself rather than what stands on it. They get
# more slack because levelling spills onto neighbours.
_TERRAFORMING = frozenset({"level_tiles", "raise_tile", "lower_tile", "demolish_tile"})
_TERRAFORM_PAD = 6


def affected_area(
    action_type: str,
    params: dict[str, Any],
    changed: dict[str, Any] | None,
    map_width: int,
    map_height: int,
) -> tuple[int, int, int, int] | None:
    """The rectangle to re-read after an action, or None if it changed no tiles.

    Returns ``(x1, y1, x2, y2)`` inclusive, clamped to the map.
    """
    if action_type not in KNOWN_ACTIONS:
        return None

    points = _points(params, changed, map_width)
    if not points:
        return None

    pad = _TERRAFORM_PAD if action_type in _TERRAFORMING else _PAD
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return (
        max(1, min(xs) - pad),
        max(1, min(ys) - pad),
        min(map_width - 2, max(xs) + pad),
        min(map_height - 2, max(ys) + pad),
    )


def _points(
    params: dict[str, Any],
    changed: dict[str, Any] | None,
    map_width: int,
) -> list[tuple[int, int]]:
    """Every coordinate the action named or reported."""
    found: list[tuple[int, int]] = []

    # Named coordinate pairs, in the shapes the dispatcher resolves.
    for x_key, y_key in (
        ("x", "y"), ("from_x", "from_y"), ("to_x", "to_y"),
        ("depot_x", "depot_y"), ("start_x", "start_y"), ("end_x", "end_y"),
        ("x1", "y1"), ("x2", "y2"),
    ):
        point = _pair(params.get(x_key), params.get(y_key))
        if point:
            found.append(point)

    # Tile indices, which the dispatcher accepts in place of any of the above.
    for key in ("tile", "tile_from", "tile_to", "depot_tile", "front_tile"):
        point = _from_tile(params.get(key), map_width)
        if point:
            found.append(point)

    # What a compound build actually did. connect_rail reports every segment it laid and
    # every gap it left, and those are the tiles that changed, whatever was asked for.
    for entry in _iter_reported(changed):
        point = _pair(entry.get("x"), entry.get("y"))
        if point:
            found.append(point)

    # A step's own path, as build_path takes it.
    for step in params.get("steps") or []:
        if isinstance(step, dict):
            point = _pair(step.get("x"), step.get("y"))
            if point:
                found.append(point)

    return found


def _iter_reported(changed: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not changed:
        return []
    out: list[dict[str, Any]] = []
    # `tile` on a successful build is [x, y] rather than a mapping, and is already covered
    # by the parameters, so only the per segment lists are read here.
    #
    # `path` is the important one and was missing. `built_tiles` was read instead, and no
    # handler has ever emitted it: the name appears nowhere in the GameScript. So on a
    # CLEAN connection, where `failed` and `gaps` are both empty by definition, the only
    # evidence left was the caller's own endpoints, and the rectangle collapsed to the
    # straight line between them. A route that detours around water or, since the slope
    # rule, around a corner it may not turn on, left that detour recorded as empty land in
    # the map every observation and every Python path is planned over.
    #
    # It does not widen the worst case: a connection's endpoints already bound the
    # rectangle, so the path only adds the margin by which the route left that box.
    for key in ("failed", "gaps", "path"):
        value = changed.get(key)
        if isinstance(value, list):
            out.extend(item for item in value if isinstance(item, dict))
    return out


def _pair(x: Any, y: Any) -> tuple[int, int] | None:
    if not _is_number(x) or not _is_number(y):
        return None
    return (int(x), int(y))


def _from_tile(tile: Any, map_width: int) -> tuple[int, int] | None:
    """A tile index back into coordinates.

    The inverse of ``y * map_width + x``, which is how every tile index in nttd is formed.
    """
    if not _is_number(tile) or map_width <= 0:
        return None
    index = int(tile)
    if index < 0:
        return None
    return (index % map_width, index // map_width)


def _is_number(value: Any) -> bool:
    """Numbers only, and a bool is not one.

    ``isinstance(True, int)`` is true in Python, and a flag parameter such as
    ``keep_rail`` would otherwise be read as the coordinate 1.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)
