"""The facts an agent is given, so it does not have to derive them.

An agent that counts its own stations and works out its own margins is spending a model
call on arithmetic, and getting it wrong makes a good decision-maker look bad at a
benchmark meant to measure judgement. So the numbers are computed and the agent decides.

The valuable part is `problems`: states that look like progress and earn nothing. A run
can sit in one of them for dozens of steps without noticing, because the observation
looks fine.
"""

from __future__ import annotations

from nttd.schemas.company import Company
from nttd.schemas.route import Route
from nttd.schemas.station import Station
from nttd.schemas.vehicle import Vehicle
from nttd.state.situation import Situation


def _situation(**kw) -> Situation:
    return Situation(
        company=kw.get("company", Company(id=0, money=100_000, loan=50_000, max_loan=300_000)),
        stations=kw.get("stations", []),
        vehicles=kw.get("vehicles", []),
        routes=kw.get("routes", []),
    )


class TestMoney:
    def test_headroom_is_what_could_still_be_borrowed(self) -> None:
        """More useful than the loan alone, which answers a question nobody asks."""
        money = _situation().report()["money"]
        assert money["headroom"] == 250_000

    def test_a_maxed_loan_has_no_headroom(self) -> None:
        s = _situation(company=Company(id=0, money=0, loan=300_000, max_loan=300_000))
        assert s.report()["money"]["headroom"] == 0

    def test_a_missing_company_does_not_raise(self) -> None:
        """Before the company exists there is nothing to report, and a crash here would
        take the whole step with it."""
        assert _situation(company=None).report()["money"]["balance"] == 0


class TestRouteHealth:
    def _route(self, **kw) -> Route:
        base = {
            "route_id": "r1", "company_id": 0, "vehicle_type": "train",
            "station_ids": [1, 2], "depot_tile": 500, "vehicle_count": 1,
            "track_confirmed_at": 700_000,
        }
        return Route(**{**base, **kw})

    def test_a_complete_route_is_working(self) -> None:
        health = _situation(routes=[self._route()]).report()["routes"][0]
        assert health["working"]
        assert health["missing"] == []

    def test_stations_without_track_are_not_a_route(self) -> None:
        """The state the old loop treated as done: both stations exist, so it moved on
        to the next pair and left this one earning nothing."""
        health = _situation(routes=[self._route(track_confirmed_at=0)]).report()["routes"][0]
        assert not health["working"]
        assert "a connection between the stations" in health["missing"]

    def test_track_without_a_vehicle_is_not_a_route(self) -> None:
        health = _situation(routes=[self._route(vehicle_count=0)]).report()["routes"][0]
        assert "a vehicle" in health["missing"]

    def test_every_missing_part_is_listed_at_once(self) -> None:
        """So one step can fix them all, rather than discovering them one at a time."""
        health = _situation(routes=[
            self._route(station_ids=[1], depot_tile=0, vehicle_count=0, track_confirmed_at=0),
        ]).report()["routes"][0]
        assert len(health["missing"]) == 4


class TestProblems:
    def test_an_unfinished_route_is_a_problem(self) -> None:
        route = Route(route_id="r1", company_id=0, vehicle_type="train",
                      station_ids=[1, 2], vehicle_count=0)
        problems = _situation(routes=[route]).report()["problems"]
        assert any("unfinished" in p["problem"] for p in problems)

    def test_a_station_nothing_calls_at_is_a_problem(self) -> None:
        """Infrastructure without vehicles earns nothing, and looks identical to
        infrastructure that is about to."""
        station = Station(id=1, name="Cufingway", company_id=0)
        problems = _situation(stations=[station]).report()["problems"]
        assert any("serves no route" in p["problem"] for p in problems)

    def test_cargo_piling_up_is_a_problem_with_the_right_advice(self) -> None:
        """It means add a vehicle to THIS route, not start another. Getting that
        backwards is how a run ends with many half-served routes."""
        station = Station(
            id=1, name="Pledington", company_id=0,
            cargo_waiting=[{"cargo_id": 1, "cargo_label": "COAL", "waiting": 250}],
        )
        route = Route(route_id="r1", company_id=0, vehicle_type="train",
                      station_ids=[1, 2], depot_tile=5, vehicle_count=1,
                      track_confirmed_at=1)
        problems = _situation(stations=[station], routes=[route]).report()["problems"]
        piling = [p for p in problems if "piling up" in p["problem"]]
        assert piling
        assert "another vehicle on this route" in piling[0]["why_it_matters"]

    def test_a_trickle_of_waiting_cargo_is_not_a_problem(self) -> None:
        """Some cargo always waits between visits. Flagging it would bury the real
        problems in noise."""
        station = Station(
            id=1, company_id=0,
            cargo_waiting=[{"cargo_id": 1, "cargo_label": "COAL", "waiting": 5}],
        )
        route = Route(route_id="r1", company_id=0, vehicle_type="train",
                      station_ids=[1, 2], depot_tile=5, vehicle_count=1,
                      track_confirmed_at=1)
        problems = _situation(stations=[station], routes=[route]).report()["problems"]
        assert not any("piling up" in p["problem"] for p in problems)

    def test_a_young_vehicle_losing_money_is_not_yet_a_problem(self) -> None:
        """Judging one too early is how a policy sells a route that was about to work."""
        young = Vehicle(id=1, company_id=0, order_count=2, profit_this_year=-9000, age=30)
        problems = _situation(vehicles=[young]).report()["problems"]
        assert not any("losing money" in p["problem"] for p in problems)

    def test_an_old_vehicle_losing_money_is_a_problem(self) -> None:
        old = Vehicle(id=1, company_id=0, order_count=2, profit_this_year=-9000, age=900)
        problems = _situation(vehicles=[old]).report()["problems"]
        assert any("losing money" in p["problem"] for p in problems)

    def test_a_vehicle_with_no_orders_is_a_problem(self) -> None:
        idle = Vehicle(id=1, company_id=0, order_count=0)
        problems = _situation(vehicles=[idle]).report()["problems"]
        assert any("no orders" in p["problem"] for p in problems)

    def test_every_problem_says_why_it_matters(self) -> None:
        """A problem an agent cannot act on is an observation. These are meant to change
        what it does next, so each carries the reason."""
        station = Station(id=1, company_id=0)
        idle = Vehicle(id=1, company_id=0, order_count=0)
        route = Route(route_id="r1", company_id=0, vehicle_type="train", station_ids=[1])
        problems = _situation(
            stations=[station], vehicles=[idle], routes=[route],
        ).report()["problems"]
        assert problems
        assert all(p["why_it_matters"] for p in problems)


class TestItIsReachable:
    def test_a_contestant_can_ask_for_it(self) -> None:
        from nttd.api.app import app

        served = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/v1/participant/sessions/{session_id}/state/situation" in served
