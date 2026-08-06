"""One tile cache per session, not one per process.

A single nttd process hosts many sessions. The cache used to be a module global created
by whichever session pathfound first, and it is not just a size: it holds height, slope,
buildability, ownership and what is built, for every tile. A second session on a
different map would have planned routes across the first session's world.

Not reachable by a contestant. connect_road and connect_rail pathfind inside the
GameScript, which runs per OpenTTD process, and this route is operator-tier. Fixed
anyway, because the next caller has no way to know that.
"""

from __future__ import annotations

import pytest

from nttd.pathfinding import service
from nttd.pathfinding.tile_cache import TileData


@pytest.fixture(autouse=True)
def _clean_caches() -> None:
    service._caches.clear()


class TestTwoSessionsDoNotShareTerrain:
    def test_each_session_gets_its_own_cache(self) -> None:
        first = service.init_cache("ses_a", 256, 256)
        second = service.init_cache("ses_b", 64, 64)
        assert first is not second

    def test_a_second_session_is_not_handed_the_first_ones_map(self) -> None:
        """The failure this prevents. Whichever session pathfound first sized the
        cache, so a 64x64 session would have been given a 256x256 world to plan in."""
        service.init_cache("ses_a", 256, 256)
        service.init_cache("ses_b", 64, 64)

        small = service.get_cache("ses_b")
        assert small is not None
        assert (small.map_width, small.map_height) == (64, 64)

    def test_tiles_loaded_for_one_session_are_invisible_to_another(self) -> None:
        """The sharper version: not just the dimensions, but the terrain."""
        first = service.init_cache("ses_a", 8, 8)
        service.init_cache("ses_b", 8, 8)

        first.set_tile(1, 1, TileData(height=9, buildable=False, water=True))

        other = service.get_cache("ses_b")
        assert other is not None
        assert other.get(1, 1) is None

    def test_an_unknown_session_has_no_cache(self) -> None:
        assert service.get_cache("never-started") is None


class TestPathfindingRefusesTheWrongSession:
    @pytest.mark.asyncio
    async def test_it_will_not_borrow_another_sessions_cache(self) -> None:
        """Asking for a session with no cache must fail rather than quietly use one
        that happens to exist, which is exactly what the global did."""
        service.init_cache("ses_a", 64, 64)

        result = await service.pathfind(
            session_id="ses_b",
            from_x=1, from_y=1, to_x=2, to_y=2,
            transport_type="road", gs_client=None,
        )
        assert result["found"] is False
        assert "not initialized" in result["error"]


class TestTheCacheIsReleased:
    def test_stopping_a_session_drops_its_tiles(self) -> None:
        """A tile record per tile, per session, for the life of the process otherwise."""
        service.init_cache("ses_a", 64, 64)
        service.drop_cache("ses_a")
        assert service.get_cache("ses_a") is None

    def test_dropping_one_leaves_the_others(self) -> None:
        service.init_cache("ses_a", 64, 64)
        service.init_cache("ses_b", 64, 64)
        service.drop_cache("ses_a")
        assert service.get_cache("ses_b") is not None

    def test_dropping_an_unknown_session_is_not_an_error(self) -> None:
        """Stop is called on paths where pathfinding never ran."""
        service.drop_cache("never-started")

    def test_the_session_manager_releases_it(self) -> None:
        import inspect

        from nttd.runtime.session_manager import SessionManager

        assert "drop_cache" in inspect.getsource(SessionManager.stop_session)
