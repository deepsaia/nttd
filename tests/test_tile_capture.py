"""Capturing the map at session start.

This routine has failed silently twice, which is why it is tested from the shape of the
reply inwards rather than by eye.

First: bounding ``get_map_terrain`` changed its reply from a list of rows to a table
wrapping them, the caller still asked whether the reply was a list, and every session
recorded no terrain at all. Second: the replies were too large for the admin protocol,
which corrupted the connection for the rest of the session, at which point everything
timed out.

``get_map_terrain`` carries occupancy and ownership now, packed into the same compact per
tile array, because terrain alone cannot answer whether anything can be built on a tile.
Reading it through ``get_tile_area`` instead was tried and is much worse: the same facts
as named fields cost about 150 characters per tile against this encoding's 12, and a full
scan through it starved the game until renaming the company timed out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import pytest

from nttd.store.tile_writer import TileWriter

# The bit layout, mirrored from the GameScript so a change there fails a test here.
WATER, COAST, BUILDABLE = 1, 2, 4
RAIL, ROAD, STATION, TREE, BRIDGE, TUNNEL = 8, 16, 32, 64, 128, 256


class _World:
    def __init__(self, width: int, height: int) -> None:
        self.game = type("Game", (), {"map_width": width, "map_height": height})()


class _FakeGameScript:
    """Answers get_map_terrain in bands, the way the real handler does."""

    def __init__(
        self,
        width: int = 30,
        height: int = 30,
        band_rows: int = 100,
        fail_at: int | None = None,
        water_row: int | None = None,
    ) -> None:
        self._width = width
        self._height = height
        self._band_rows = band_rows
        self._fail_at = fail_at
        self._water_row = water_row
        self.calls: list[dict[str, Any]] = []

    async def send_gamescript(
        self, command: str, params: dict[str, Any], timeout: float = 0,
    ) -> dict[str, Any]:
        assert command == "get_map_terrain"
        self.calls.append(dict(params))
        from_y = params.get("from_y", 1)
        if self._fail_at is not None and from_y >= self._fail_at:
            return {"success": False, "error": "gs timeout"}

        to_y = min(from_y + self._band_rows - 1, self._height)
        truncated = to_y < self._height
        rows = []
        for y in range(from_y, to_y + 1):
            tiles = []
            for x in range(1, self._width + 1):
                flags = WATER if y == self._water_row else BUILDABLE
                if x == 1:
                    flags |= RAIL
                if x == 2:
                    flags |= STATION
                if x == 3:
                    flags |= BRIDGE
                if x == 4:
                    flags |= TUNNEL
                tiles.append([3, 0, flags, 0 if x == 1 else -1])
            rows.append({"y": y, "tiles": tiles})
        return {"success": True, "result": {
            "rows": rows, "from_y": from_y, "to_y": to_y,
            "truncated": truncated,
            "next_from_y": to_y + 1 if truncated else None,
        }}


class _Runtime:
    """The three collaborators _capture_tiles touches, and nothing else."""

    def __init__(self, session_id: str, admin_client: Any, tile_writer: TileWriter,
                 world: _World) -> None:
        self.session_id = session_id
        self.admin_client = admin_client
        self.tile_writer = tile_writer
        self.world = world


def _runtime(tmp_path: Path, gs: Any) -> _Runtime:
    from nttd.runtime.session_runtime import SessionRuntime

    runtime = _Runtime(
        "ses_t", gs, TileWriter("ses_t", data_dir=str(tmp_path)), _World(32, 32),
    )
    # Borrowed rather than reimplemented, so this tests the shipped routine, including
    # the shared terrain scan it now delegates the paging to.
    runtime._capture_tiles = SessionRuntime._capture_tiles.__get__(runtime, _Runtime)
    runtime._ask_gamescript = SessionRuntime._ask_gamescript.__get__(runtime, _Runtime)
    return runtime


def _tiles(tmp_path: Path) -> pl.DataFrame:
    path = tmp_path / "ses_t" / "tiles.parquet"
    if not path.exists():
        return pl.DataFrame()
    return pl.read_parquet(path)


# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_single_band_map_is_captured_whole(tmp_path: Path) -> None:
    gs = _FakeGameScript(width=30, height=20, band_rows=50)
    await _runtime(tmp_path, gs)._capture_tiles()
    assert len(_tiles(tmp_path)) == 30 * 20
    assert len(gs.calls) == 1


@pytest.mark.asyncio
async def test_a_map_larger_than_one_band_is_paged_until_complete(tmp_path: Path) -> None:
    """The regression that recorded nothing at all for weeks."""
    gs = _FakeGameScript(width=30, height=100, band_rows=25)
    await _runtime(tmp_path, gs)._capture_tiles()
    frame = _tiles(tmp_path)
    assert len(frame) == 30 * 100
    assert sorted(frame["y"].unique().to_list()) == list(range(1, 101))
    assert len(gs.calls) == 4


@pytest.mark.asyncio
async def test_paging_resumes_where_the_handler_says_to(tmp_path: Path) -> None:
    gs = _FakeGameScript(width=10, height=30, band_rows=10)
    await _runtime(tmp_path, gs)._capture_tiles()
    assert [call["from_y"] for call in gs.calls] == [1, 11, 21]


@pytest.mark.asyncio
async def test_occupancy_and_ownership_are_recorded(tmp_path: Path) -> None:
    """The point of widening the encoding: terrain alone cannot say whether a tile is
    taken or whose the track on it is, which is most of what a route needs."""
    await _runtime(tmp_path, _FakeGameScript())._capture_tiles()
    frame = _tiles(tmp_path)
    for column in ("owner", "has_rail", "has_road", "is_station", "has_tree"):
        assert column in frame.columns, column
    assert frame.filter(pl.col("x") == 1)["has_rail"].all()
    assert frame.filter(pl.col("x") == 1)["owner"].max() == 0
    assert frame.filter(pl.col("x") == 2)["is_station"].all()
    assert not frame.filter(pl.col("x") == 5)["has_rail"].any()


@pytest.mark.asyncio
async def test_bridges_and_tunnels_are_recorded(tmp_path: Path) -> None:
    """A crossing used to read as owned, unbuildable and nothing else."""
    await _runtime(tmp_path, _FakeGameScript())._capture_tiles()
    frame = _tiles(tmp_path)
    assert frame.filter(pl.col("x") == 3)["has_bridge"].all()
    assert frame.filter(pl.col("x") == 4)["has_tunnel"].all()
    assert not frame.filter(pl.col("x") == 5)["has_bridge"].any()


@pytest.mark.asyncio
async def test_the_flags_bitmask_survives_for_the_terrain_reports(tmp_path: Path) -> None:
    """prepare_terrain_grid masks bit 0 of this column for water, and the terrain map and
    the video both go through it. Widening the mask must not disturb the low bits."""
    await _runtime(tmp_path, _FakeGameScript(water_row=5))._capture_tiles()
    frame = _tiles(tmp_path)
    water = frame.filter((pl.col("y") == 5) & (pl.col("x") > 4))
    land = frame.filter((pl.col("y") == 6) & (pl.col("x") > 4))
    assert (water["flags"] & WATER).min() == WATER
    assert (land["flags"] & WATER).max() == 0
    assert (land["flags"] & BUILDABLE).min() == BUILDABLE


@pytest.mark.asyncio
async def test_a_failed_band_writes_nothing_rather_than_a_partial_grid(
    tmp_path: Path,
) -> None:
    """A half grid on disk is indistinguishable from a small map."""
    gs = _FakeGameScript(width=10, height=100, band_rows=10, fail_at=21)
    await _runtime(tmp_path, gs)._capture_tiles()
    assert _tiles(tmp_path).is_empty()


@pytest.mark.asyncio
async def test_a_list_reply_is_no_longer_accepted(tmp_path: Path) -> None:
    """The old shape. Accepting it silently is how the scan broke before."""

    class _OldShape:
        calls: list[dict[str, Any]] = []

        async def send_gamescript(
            self, command: str, params: dict[str, Any], timeout: float = 0,
        ) -> dict[str, Any]:
            return {"success": True, "result": [{"y": 1, "tiles": [[1, 0, 4]]}]}

    await _runtime(tmp_path, _OldShape())._capture_tiles()
    assert _tiles(tmp_path).is_empty()


@pytest.mark.asyncio
async def test_a_handler_that_cannot_say_where_to_resume_does_not_spin(
    tmp_path: Path,
) -> None:
    """Without the guard this asked for the same band forever."""

    class _Stuck(_FakeGameScript):
        async def send_gamescript(
            self, command: str, params: dict[str, Any], timeout: float = 0,
        ) -> dict[str, Any]:
            reply = await super().send_gamescript(command, params, timeout)
            reply["result"]["truncated"] = True
            reply["result"]["next_from_y"] = None
            return reply

    gs = _Stuck(width=10, height=10, band_rows=10)
    await _runtime(tmp_path, gs)._capture_tiles()
    assert len(gs.calls) == 1
    assert len(_tiles(tmp_path)) == 100


@pytest.mark.asyncio
async def test_a_reply_without_owners_still_loads(tmp_path: Path) -> None:
    """An older GameScript sends three values per tile rather than four."""

    class _ThreeValues(_FakeGameScript):
        async def send_gamescript(
            self, command: str, params: dict[str, Any], timeout: float = 0,
        ) -> dict[str, Any]:
            reply = await super().send_gamescript(command, params, timeout)
            for row in reply["result"]["rows"]:
                row["tiles"] = [tile[:3] for tile in row["tiles"]]
            return reply

    await _runtime(tmp_path, _ThreeValues(width=5, height=5))._capture_tiles()
    frame = _tiles(tmp_path)
    assert len(frame) == 25
    assert frame["owner"].max() == -1
