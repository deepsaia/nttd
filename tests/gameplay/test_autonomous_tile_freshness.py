"""The stored map hears about changes the contestant did not make.

nttd sees every contestant action and re-reads the tiles it touched, even on failure, so that
half of map freshness was already covered. The world also changes on its own, and that was
not: an industry that opened stood on tiles the stored map still called empty, and a route
planned over them was planned over a fiction.

Three events say where it happened, so three events now trigger a re-read. Town GROWTH is
absent on purpose: OpenTTD raises no event for it, so houses and roads appearing as a town
expands are left to heal on contact.
"""

from __future__ import annotations

import asyncio
from typing import Any

from nttd.runtime.orchestrator import (
    _WORLD_CHANGE_EVENTS,
    _WORLD_CHANGE_PAD,
    Orchestrator,
)


class _Recorded:
    """A stand-in for the tile writer, keeping what it was handed."""

    def __init__(self) -> None:
        self.deltas: list[list[dict[str, Any]]] = []

    def write_delta(self, tiles: list[dict[str, Any]]) -> None:
        self.deltas.append(tiles)


def _orchestrator(width: int = 256, height: int = 256) -> Orchestrator:
    """An orchestrator with only the parts this behaviour touches."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.tile_writer = _Recorded()
    orch.recorder = None
    orch.world = type("W", (), {"game": type("G", (), {
        "map_width": width, "map_height": height,
    })()})()
    orch._read_areas: list[tuple[int, int, int, int]] = []

    async def _read(x1: int, y1: int, x2: int, y2: int) -> list[dict[str, Any]]:
        orch._read_areas.append((x1, y1, x2, y2))
        return [{"x": x1, "y": y1}]

    orch._read_tile_area = _read
    return orch


def test_the_three_autonomous_events_are_the_ones_watched() -> None:
    """Named rather than inferred, so adding a fourth is a decision and not an accident."""
    assert _WORLD_CHANGE_EVENTS == {"industry_open", "industry_close", "town_founded"}


def test_an_industry_opening_refreshes_its_neighbourhood() -> None:
    orch = _orchestrator()
    asyncio.run(orch._refresh_around("industry_open", 100, 120))

    assert orch._read_areas == [(
        100 - _WORLD_CHANGE_PAD, 120 - _WORLD_CHANGE_PAD,
        100 + _WORLD_CHANGE_PAD, 120 + _WORLD_CHANGE_PAD,
    )]
    assert len(orch.tile_writer.deltas) == 1


def test_the_area_is_clamped_to_the_map() -> None:
    """An industry near the edge must not ask for tile minus five."""
    orch = _orchestrator(width=64, height=64)
    asyncio.run(orch._refresh_around("town_founded", 2, 61))

    (x1, y1, x2, y2) = orch._read_areas[0]
    assert x1 >= 1 and y1 >= 1
    assert x2 <= 62 and y2 <= 62


def test_an_event_with_no_coordinates_refreshes_nothing() -> None:
    """A closing industry may already be unresolvable when the event fires. Skipping is
    right; refreshing a rectangle around tile 0 would be worse than doing nothing."""
    orch = _orchestrator()
    orch._schedule_world_refresh("industry_close", {"industry_id": 7})
    assert orch._read_areas == []
    assert orch.tile_writer.deltas == []


def test_a_session_with_no_tile_writer_is_left_alone() -> None:
    orch = _orchestrator()
    orch.tile_writer = None
    asyncio.run(orch._refresh_around("industry_open", 50, 50))
    assert orch._read_areas == []


def test_a_read_failure_does_not_escape() -> None:
    """A stale map is a worse map, not a broken run."""
    orch = _orchestrator()

    async def _boom(x1: int, y1: int, x2: int, y2: int) -> list[dict[str, Any]]:
        raise RuntimeError("the game was busy")

    orch._read_tile_area = _boom
    asyncio.run(orch._refresh_around("industry_open", 10, 10))
    assert orch.tile_writer.deltas == []
