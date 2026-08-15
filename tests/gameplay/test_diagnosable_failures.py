"""Every failure a query can be asked about says why, instead of looking like success.

Each case here was a silent failure: a halted vehicle that read as running, an industry whose
cargo went to a station nobody served, an airport sited outside its own catchment, a finder that
answered "tile parameter required" when asked in the obvious way, and a crash event that named
neither the vehicle nor the place. In every one the information existed and was thrown away.

Asserted against main.nut and the generated manifest rather than a live game, because these are
contract changes: what the reply CARRIES. Whether the numbers are right is a question for a live
session, and each of these was found by one.

Every fix here is a new return field or a widened parameter set, which is why nothing in the HTTP
or MCP layers needed touching: HTTP passes GameScript replies through unchanged, and MCP builds
its action enums from the manifest at import. Only a NEW ACTION needs registering by hand, in
constants.py for its tier and descriptions.json for its prose.
"""

from __future__ import annotations

import json

from tests.conftest import REPO_ROOT

_ROOT = REPO_ROOT
_GS = (_ROOT / "ottd_config" / "game" / "nttd-gs" / "main.nut").read_text()
_ACTIONS = json.loads((_ROOT / "config" / "actions" / "manifest.json").read_text())["actions"]


def _returns(action: str) -> list[str]:
    return (_ACTIONS[action].get("returns") or {}).get("fields", [])


class TestAVehicleSaysWhyItIsNotMoving:
    """A halted vehicle answered state 0 and speed 0, the same as one waiting at a signal.

    Three measured cases: a train stopped for twelve days on a verified line; a train rocking
    inside an unjoined depot at speeds of 0, 39, 21, 36 without ever changing tile; and a ship
    built in one sea ordered to a dock in another. Detecting any of them meant polling position
    across steps, which spends the steps a contestant is scored on.
    """

    def test_the_reply_carries_the_games_own_lost_flag(self) -> None:
        assert "lost" in _returns("get_vehicle_info")

    def test_the_reply_says_why_it_is_idle(self) -> None:
        assert "idle_reason" in _returns("get_vehicle_info")

    def test_lost_comes_from_the_games_event_and_not_from_a_guess(self) -> None:
        """ET_VEHICLE_LOST is the only authoritative signal; the GS already received it and
        threw it away."""
        assert "ET_VEHICLE_LOST && (\"vehicle_id\" in payload)" in _GS
        assert "_lost_vehicles[vid] <- GSVehicle.GetLocation(vid)" in _GS

    def test_the_flag_clears_when_the_vehicle_moves(self) -> None:
        """There is no "found" event, so a flag that only ever sets would be permanent."""
        assert "delete this._lost_vehicles[vid]" in _GS

    def test_the_idle_reasons_separate_the_fixes(self) -> None:
        """Stopped, in a depot and no-path need three different actions taken."""
        for reason in ('"stopped"', '"in_depot"', '"no_path"', '"at_station"', '"broken_down"'):
            assert reason in _GS, reason


class TestAnIndustrySaysWhichStationCollects:
    """A leftover station four tiles away took 422 units of wood for 120 days while the station
    the train served showed nothing. An industry delivers to ONE station, and not necessarily
    the nearest or the newest.
    """

    def test_industries_report_the_stations_in_range(self) -> None:
        assert "served_by" in _returns("get_industries")

    def test_it_lists_them_rather_than_naming_a_winner(self) -> None:
        """Catchment differs by station type. More than one in range is the warning worth
        having; asserting which one wins would be a guess presented as a fact."""
        assert "station_id = sid" in _GS
        assert "distance = distance" in _GS

    def test_the_station_list_is_read_inside_a_company_mode(self) -> None:
        """GSStationList is EMPTY outside one, exactly as GSVehicleList is. That trap cost an
        hour and made four counters read zero while the game reported 222 units delivered."""
        serving = _GS[_GS.index("function _ServingStations"):]
        serving = serving[:serving.index("function _IsLost")]
        # Comments stripped: the explanation names GSStationList before the code reaches it, and
        # matching prose would pass whatever the code did.
        code = "\n".join(
            line for line in serving.splitlines() if not line.strip().startswith("//")
        )
        assert "GSCompanyMode(0)" in code
        assert code.index("GSCompanyMode(0)") < code.index("GSStationList")


class TestTheAirportFinderReportsWhatDecidesTheRoute:
    """Airports 16 to 28 tiles from their towns earned nothing: a town of 4,379 people offered
    one waiting passenger, because a commuter airport reaches 4 tiles. Coverage was not in the
    reply that chooses the site.
    """

    def test_coverage_is_reported(self) -> None:
        assert "coverage" in _returns("find_airport_spots")

    def test_the_answer_is_given_directly_as_well(self) -> None:
        """A reader should not have to compare two numbers to learn the site is useless."""
        assert "within_coverage" in _returns("find_airport_spots")

    def test_it_comes_from_the_game_rather_than_a_table_of_ours(self) -> None:
        assert "GSAirport.GetAirportCoverageRadius(airport_type)" in _GS


class TestTheRailDepotFinderTakesWhatItsSiblingsTake:
    """It demanded a tile index where every sibling takes town_id or x/y, and answered a bare
    "tile parameter required" that reads like there being nowhere to put a depot.
    """

    def test_it_accepts_a_town_or_coordinates_now(self) -> None:
        params = set(_ACTIONS["find_rail_depot_spot"]["parameters"])
        assert {"town_id", "x", "y", "tile"} <= params

    def test_tile_is_no_longer_required(self) -> None:
        assert not _ACTIONS["find_rail_depot_spot"]["parameters"]["tile"].get("required")


class TestAnEventThatCannotBeReadSaysSo:
    """Three aircraft and roughly 150,000 disappeared behind two `vehicle_crashed` events that
    carried no vehicle, no place and no cause. The extraction threw, a catch swallowed it, and
    the bare payload went out. GSLog.Warning does not reach openttd.log at the default level
    either, so the loss was invisible twice over.
    """

    def test_a_failed_extraction_is_reported_in_the_payload(self) -> None:
        assert 'payload.rawset("extract_error"' in _GS

    def test_it_is_logged_at_a_level_that_reaches_the_log(self) -> None:
        forwarder = _GS[_GS.index("function _ForwardGameEvent"):]
        forwarder = forwarder[:forwarder.index("GSAdmin.Send(payload)")]
        assert "GSLog.Error(\"nttd: could not process event type" in forwarder


class TestJoiningADepotIsOneAction:
    """Joining a rail depot to its line took four actions, a direction-bit mapping and a slope
    check, and it took three attempts to get right by hand. There is no judgement in any of it.

    connect_rail cannot do the job: it lays rail on BOTH endpoints, so aimed at a depot it fails
    ERR_AREA_NOT_CLEAR against the very depot it is trying to reach.
    """

    def test_the_action_exists_and_a_contestant_may_use_it(self) -> None:
        assert _ACTIONS["connect_depot"]["tier"] == "participant"

    def test_it_takes_a_tile_or_coordinates(self) -> None:
        assert {"tile", "x", "y"} <= set(_ACTIONS["connect_depot"]["parameters"])

    def test_it_says_where_it_joined_and_whether_it_had_to(self) -> None:
        """An action that reports nothing leaves the caller to re-derive what happened."""
        fields = _returns("connect_depot")
        assert "joined_at" in fields
        assert "already_connected" in fields

    def test_it_refuses_a_platform_rather_than_failing_obscurely(self) -> None:
        """A station platform sets the rail bit but can never take a track piece, and every
        attempt there returns a bare ERR_AREA_NOT_CLEAR."""
        assert "that neighbour is a station platform, not running line" in _GS

    def test_a_failure_lists_what_it_tried(self) -> None:
        assert "tried" in _returns("connect_depot")

    def test_the_new_action_is_registered_in_every_layer(self) -> None:
        """A new action is the ONE case that needs hand-registration: its tier in constants.py
        and its prose in descriptions.json. Return fields and parameters do not."""
        from nttd.constants import KNOWN_ACTIONS
        from nttd.mcp.action_types import PlayableAction

        assert "connect_depot" in KNOWN_ACTIONS, "HTTP accepts it"
        assert "connect_depot" in [a.value for a in PlayableAction], "MCP exposes it"
        assert _ACTIONS["connect_depot"]["gamescript_function"] == "CmdConnectDepot"


class TestTheTerrainSeparatesTrackFromPlatform:
    """Flags 40 is rail|station, so "where is the running line" could not be answered: a depot
    placed against a platform can never be joined, and the attempt returns ERR_AREA_NOT_CLEAR
    without saying why. And nothing reported depots at all, because OpenTTD does not treat one
    as a station.
    """

    def test_running_line_has_its_own_bit(self) -> None:
        assert "if ((flags & 8) && !(flags & 32)) flags = flags | 512" in _GS
        assert "if ((flags & 16) && !(flags & 32)) flags = flags | 1024" in _GS

    def test_depots_are_reported(self) -> None:
        assert "flags | 2048" in _GS
        for probe in ("IsRailDepotTile", "IsRoadDepotTile", "IsWaterDepotTile"):
            assert probe in _GS, probe

    def test_the_bits_are_documented_where_the_reply_is_described(self) -> None:
        """A bit field nobody can decode is not an observation."""
        described = (_ROOT / "docs" / "actions" / "observations.md").read_text()
        assert "512 rail RUNNING LINE" in described
        assert "2048 depot" in described


class TestThePreFlightChecksAnswerTheQuestionAsked:
    """Two checks an agent makes before spending, both of which lied.

    trace_route walks existing track. Its TRACK geometry was always right: each step asks the
    game whether a vehicle can come from the previous tile, through this one, to the next, so a
    curve that does not join is rejected. What it got wrong was the very first hop, where there
    is no previous tile and it invented one.

    plan_route plans a BUILD. It was called check_connection, which is a different question, and
    the name is why it was reached for as a connectivity test and answered zero on water.
    """

    def test_the_first_hop_no_longer_invents_an_approach(self) -> None:
        """The measured failure: a depot the game reported connected, whose train then ran at
        107 km/h, traced as line_exists false with tiles_reachable 1."""
        assert "if (node.tile == start) {" in _GS
        walk = _GS[_GS.index("function CmdTraceRoute"):]
        walk = walk[:walk.index("local reachable = 0")]
        # Adjacency for the first hop, the full triple test after it.
        assert "joined = is_track;" in walk
        assert "GSRail.AreTilesConnected(prev, node.tile, next)" in walk

    def test_it_says_what_it_does_not_model(self) -> None:
        """A check that cannot be exact has to say so, or it gets trusted as if it were."""
        described = _ACTIONS["trace_route"]["description"]
        for limit in ("platform", "reverse", "signals"):
            assert limit in described, limit
        assert "lost" in described, "points at the one exact answer there is"

    def test_the_build_planner_is_named_for_what_it_plans(self) -> None:
        from nttd.api import observation_routes

        assert hasattr(observation_routes, "plan_route")
        assert not hasattr(observation_routes, "check_path")

    def test_a_dock_is_seeded_from_the_water_beside_it(self) -> None:
        """A dock occupies a station tile and the water walker crosses only water, so both
        endpoints were rejected: dock to dock gave 0 tiles for routes being sailed."""
        from nttd.pathfinding.service import _water_beside

        class _Tile:
            def __init__(self, water: bool) -> None:
                self.water = water

        class _Cache:
            def __init__(self, water: set[tuple[int, int]]) -> None:
                self._water = water

            def get(self, x: int, y: int) -> _Tile | None:
                return _Tile((x, y) in self._water)

        # A dock at (10,10) with water to its east.
        cache = _Cache({(11, 10)})
        assert _water_beside(cache, 10, 10) == (11, 10)
        # Open water is returned untouched, so a caller passing water is unaffected.
        assert _water_beside(cache, 11, 10) == (11, 10)
        # Nothing adjacent is water: unchanged rather than guessed.
        assert _water_beside(_Cache(set()), 10, 10) == (10, 10)


class TestABridgeIsBuiltWithATypeThatFits:
    """A 29 tile corridor whose plan asked for one bridge lost its crossing and the route died.

    I recorded that as "build_path does not build bridges". It was wrong: the handler has always
    had a build_bridge branch, reports every failed step in `failed`, and returns status
    "partial" with success false. My builder ignored the reply and inferred the failure from a
    later connectivity check.

    The real fault was narrower. The branch hardcoded bridge type 0, and bridge availability
    depends on span and on year, so where type 0 cannot span the gap no bridge is built at all.
    """

    def test_the_type_is_chosen_by_the_span_rather_than_hardcoded(self) -> None:
        branch = _GS[_GS.index('if (action == "build_bridge") {'):]
        branch = branch[:branch.index('if (action == "build_tunnel")')]
        assert "GSBridgeList_Length(span)" in branch
        assert "local bt = 0;" not in branch, "the hardcoded type is gone"

    def test_an_explicit_type_still_wins(self) -> None:
        """A caller wanting a fast bridge rather than a cheap one must still be able to say so."""
        branch = _GS[_GS.index('if (action == "build_bridge") {'):]
        branch = branch[:branch.index('if (action == "build_tunnel")')]
        assert '("bridge_type" in step)' in branch

    def test_a_failure_reports_the_span_it_could_not_cross(self) -> None:
        """"Could not build" is not actionable; "nothing spans 5 tiles" is."""
        branch = _GS[_GS.index('if (action == "build_bridge") {'):]
        branch = branch[:branch.index('if (action == "build_tunnel")')]
        assert "span = span" in branch
        assert "types_tried" in branch

    def test_the_build_already_refused_to_claim_success(self) -> None:
        """Worth pinning, because I misread this as a silent failure once and it is not: a
        partial build says so, and names every step that failed."""
        assert "status = complete ? \"complete\" : \"partial\"" in _GS
        assert "success = complete," in _GS


def test_no_http_or_mcp_change_was_needed_for_any_of_these() -> None:
    """All of the above are return fields or widened parameters, and both layers are generic:
    HTTP passes the GameScript reply through, and MCP builds its enums from the manifest. This
    pins that, so a future change that quietly special-cases a field gets noticed.
    """
    from nttd.mcp import action_types

    assert "find_rail_depot_spot" in [a.value for a in action_types.ObservationAction]
    assert "get_vehicle_info" in [a.value for a in action_types.ObservationAction]


def test_a_lost_vehicle_says_so_in_the_observation() -> None:
    """The GameScript reporting it is only half the path.

    WorldState builds each Vehicle from an explicit field list, and lost/idle_reason were not
    on it, so both arrived as their defaults however clearly the game had answered. Measured:
    a train sat in the far corner of the map for 130 days, every station empty and zero cargo
    delivered, and the observation said lost=None. The same omission on the company side scored
    every run at zero cargo, so this is the second instance of one mistake.
    """
    from nttd.state.world import WorldState

    world = WorldState()
    world.apply_gs_vehicles(0, [{
        "id": 21, "type": "train", "x": 39, "y": 40,
        "lost": True, "idle_reason": "no_path",
    }])

    vehicle = world.vehicles[21]
    assert vehicle.lost is True
    assert vehicle.idle_reason == "no_path"
