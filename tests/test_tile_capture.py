"""Capturing the map's terrain at session start.

This exists because the capture broke silently. ``get_map_terrain`` was bounded so an
agent could not ask for a 524 KB reply, which changed its result from a list of rows to a
table carrying those rows. The caller still asked whether the result was a list, so from
that moment every session recorded no terrain, and the only sign was a warning in a log
nobody reads plus an empty terrain report much later.

So the shape of the reply is pinned here, and so is the paging: a partial grid that looks
complete is the same failure wearing a different hat.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import pytest

from nttd.runtime.session_runtime import _TILE_SCAN_BAND
from nttd.store.tile_writer import TileWriter


class _FakeGameScript:
    """Answers get_map_terrain in bands, the way the real handler does."""

    def __init__(self, width: int, height: int, band_rows: int, fail_at: int | None = None) -> None:
        self._width = width
        self._height = height
        self._band_rows = band_rows
        self._fail_at = fail_at
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
        rows = [
            {"y": y, "tiles": [[1, 0, 4] for _ in range(self._width)]}
            for y in range(from_y, to_y + 1)
        ]
        return {"success": True, "result": {
            "rows": rows,
            "from_y": from_y,
            "to_y": to_y,
            "truncated": truncated,
            "next_from_y": to_y + 1 if truncated else None,
            "tiles_returned": len(rows) * self._width,
        }}


class _StuckGameScript(_FakeGameScript):
    """Claims it truncated but never says where to resume."""

    async def send_gamescript(
        self, command: str, params: dict[str, Any], timeout: float = 0,
    ) -> dict[str, Any]:
        reply = await super().send_gamescript(command, params, timeout)
        if reply.get("success"):
            reply["result"]["truncated"] = True
            reply["result"]["next_from_y"] = None
        return reply


class _Runtime:
    """The two collaborators _capture_tiles touches, and nothing else."""

    def __init__(self, session_id: str, admin_client: Any, tile_writer: TileWriter) -> None:
        self.session_id = session_id
        self.admin_client = admin_client
        self.tile_writer = tile_writer

    _capture_tiles = None  # bound below


def _runtime(tmp_path: Path, gs: Any) -> _Runtime:
    from nttd.runtime.session_runtime import SessionRuntime

    runtime = _Runtime("ses_t", gs, TileWriter("ses_t", data_dir=str(tmp_path)))
    # Borrowed rather than reimplemented, so this tests the shipped routine.
    runtime._capture_tiles = SessionRuntime._capture_tiles.__get__(runtime, _Runtime)
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
    """The regression. One band used to be the whole capture, and now it is not."""
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
async def test_the_scan_asks_for_the_handlers_full_ceiling(tmp_path: Path) -> None:
    """nttd reading its own game over a local socket wants the fewest round trips."""
    gs = _FakeGameScript(width=10, height=10, band_rows=10)
    await _runtime(tmp_path, gs)._capture_tiles()
    assert gs.calls[0]["max_tiles"] == _TILE_SCAN_BAND


@pytest.mark.asyncio
async def test_a_failed_band_writes_nothing_rather_than_a_partial_grid(
    tmp_path: Path,
) -> None:
    """A half grid on disk is indistinguishable from a small map."""
    gs = _FakeGameScript(width=10, height=100, band_rows=10, fail_at=21)
    await _runtime(tmp_path, gs)._capture_tiles()
    assert _tiles(tmp_path).is_empty()


@pytest.mark.asyncio
async def test_a_handler_that_cannot_say_where_to_resume_does_not_spin(
    tmp_path: Path,
) -> None:
    """Without the guard this asked for the same band forever."""
    gs = _StuckGameScript(width=10, height=10, band_rows=10)
    await _runtime(tmp_path, gs)._capture_tiles()
    assert len(gs.calls) == 1
    assert len(_tiles(tmp_path)) == 100


@pytest.mark.asyncio
async def test_a_list_reply_is_no_longer_accepted(tmp_path: Path) -> None:
    """The old shape must not quietly half work if something replays it."""

    class _OldShape:
        calls: list[dict[str, Any]] = []

        async def send_gamescript(
            self, command: str, params: dict[str, Any], timeout: float = 0,
        ) -> dict[str, Any]:
            return {"success": True, "result": [{"y": 1, "tiles": [[1, 0, 4]]}]}

    await _runtime(tmp_path, _OldShape())._capture_tiles()
    assert _tiles(tmp_path).is_empty()
