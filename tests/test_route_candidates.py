"""Which routes an agent is told are worth building.

`RoutePlanner` is 340 lines of exactly the right abstraction, with a `for_agent` method
whose own docstring says it is for "the live agent observation pipeline". It was
unreachable: its only importers were two offline report generators, so the component
built to tell an agent which routes pay was used only to draw charts afterwards.

The water classification was also circular. It offered water only where a dock already
stood within 15 tiles of BOTH endpoints, and docks are built from stations, so at turn
one a water agent was told there was nothing to do. It was the wrong question too: the
arguments were named has_water_src while measuring existing infrastructure.
"""

from __future__ import annotations

from nttd.state.route_planner import (
    AIR_MIN_DISTANCE,
    ROAD_MAX_DISTANCE,
    WATER_MAX_DISTANCE,
    classify_transport_modes,
)


class TestWaterIsNotGatedOnExistingDocks:
    def test_a_short_route_offers_water_with_no_docks_anywhere(self) -> None:
        """The circularity, directly. Before the fix this returned no water at all."""
        modes = classify_transport_modes(
            distance=30, docks_at_src=False, docks_at_dst=False, cargo="COAL",
        )
        assert "water" in modes

    def test_a_long_route_does_not_offer_water(self) -> None:
        """Ships are slow enough that a long route is hundreds of game-days at no
        revenue. Offering it would be worse than offering nothing."""
        modes = classify_transport_modes(
            distance=WATER_MAX_DISTANCE + 40,
            docks_at_src=False, docks_at_dst=False, cargo="COAL",
        )
        assert "water" not in modes

    def test_existing_docks_still_offer_water_at_any_distance(self) -> None:
        """A pair already served by ships is proven, whatever the distance."""
        modes = classify_transport_modes(
            distance=500, docks_at_src=True, docks_at_dst=True, cargo="COAL",
        )
        assert "water" in modes


class TestTheOtherModesAreUnchanged:
    def test_rail_is_always_offered(self) -> None:
        assert "rail" in classify_transport_modes(5, False, False, "COAL")
        assert "rail" in classify_transport_modes(500, False, False, "COAL")

    def test_road_is_offered_only_when_short_enough(self) -> None:
        assert "road" in classify_transport_modes(ROAD_MAX_DISTANCE, False, False, "COAL")
        assert "road" not in classify_transport_modes(ROAD_MAX_DISTANCE + 1, False, False, "COAL")

    def test_air_needs_distance_and_the_right_cargo(self) -> None:
        assert "air" in classify_transport_modes(AIR_MIN_DISTANCE, False, False, "PASS")
        assert "air" not in classify_transport_modes(AIR_MIN_DISTANCE, False, False, "COAL")
        assert "air" not in classify_transport_modes(AIR_MIN_DISTANCE - 1, False, False, "PASS")


class TestItIsReachable:
    def test_the_participant_tier_serves_it(self) -> None:
        """The whole point. Measured live on a 256x256 seed 1001 session at turn one:
        general 159 cargo routes, road 31, water 20, air 153 town routes. Water was
        zero before the fix, by construction."""
        from nttd.api.app import app

        served = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/v1/participant/sessions/{session_id}/state/routes" in served

    def test_it_is_not_operator_only(self) -> None:
        from nttd.api.app import app

        served = {r.path for r in app.routes if hasattr(r, "path")}
        assert not any(
            p.endswith("/state/routes") and "/operator/" in p for p in served
        ), "route candidates must be reachable by a contestant, not just an operator"
