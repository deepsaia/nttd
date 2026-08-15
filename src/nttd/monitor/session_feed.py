"""One session's history, shaped for charting, live or ended.

Everything here comes from ``analysis.loader.load_session``, which already resolves the
one distinction that matters: a running session has per step fragments under
``_fragments/``, and an ended one has merged parquet. Reading only fragments reports
nothing the moment a run finishes, and reading only merged files reports nothing while it
is still going. Both mistakes look like a legitimately empty session, which is how a
summary can silently print zeros for a run that built 22 stations.

The scalar series and the world objects are separated on purpose. The charts need 31 rows
of numbers; the map needs the object lists, which are two orders of magnitude larger. The
towns and industries barely change over a run, so they are published once as a static
layer, and only stations and vehicles are published per step. That keeps the page a page
rather than a download.
"""

from __future__ import annotations

import json
from typing import Any

from nttd.analysis.date_utils import game_date_to_ymd
from nttd.analysis.loader import SessionData
from nttd.utils.name_generator import readable_part

# The NETWORK pieces a company owns: the things a vehicle travels along. Named here rather
# than discovered from the data so a mode that built none of something still gets a labelled
# zero series instead of vanishing from the legend.
#
# Stations and airports used to be in this list, and they do not belong: a station tile is not
# a piece of network, it is a place vehicles stop. Counting them beside rail pieces put a
# number in the tens next to a number in the hundreds, and read as if the company had built
# almost no stations. They are charted against vehicles instead, which is the comparison that
# means something.
INFRA_KINDS = ("rail", "road", "water")

# The station-like things a company owns, counted per step. Every one of these is somewhere a
# vehicle stops, so they belong on the same chart as the fleet that stops at them. Depots are
# absent because the snapshot does not report them: OpenTTD does not treat a depot as a
# station, so there is nothing to count without inventing it.
STATION_KINDS = ("rail", "bus", "truck", "dock", "air")

# The vehicle types a company can own, as the snapshot spells them. Charted on their own
# rather than beside the stations: a fleet and the places it stops are two different
# quantities, and one chart carrying both was nine series deep and unreadable.
VEHICLE_KINDS = ("train", "road", "ship", "aircraft")


class SessionFeed:
    """The per-step view of one session."""

    def __init__(self, data: SessionData) -> None:
        self._data = data
        self._parsed: list[dict[str, Any]] | None = None
        self._last: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def meta(self) -> dict[str, Any]:
        """What this session is, and whether it is still going.

        Reads only the newest snapshot. The index page builds one of these per session,
        and parsing every step of every session to fill a table of latest figures is the
        difference between a page that loads and one that crawls once a few dozen
        sessions have accumulated.
        """
        data = self._data
        last = self._latest()
        game = last.get("game") or {}
        company = self._company(last)
        return {
            "session_id": data.session_id,
            # The company's own generated name, which is what identifies a run: the
            # session's name is the scenario slot it filled, and four concurrent runs of
            # one scenario all carry the same one.
            "name": company.get("name") or data.name or data.session_id,
            # The words out of the id. A session is now named once, as
            # 20260815-073255-dandy-willow, and a sidebar that repeats the date on every
            # row beside a Date column spends its width saying the same thing twice.
            "session_name": readable_part(data.name or data.session_id),
            "scenario": data.config_name,
            "description": data.description,
            "model": data.model,
            "status": data.status,
            # Unmerged fragments mean "running OR stopped uncleanly", which is not the
            # same as live. Whether it is actually live depends on how long ago it last
            # wrote, and only the registry knows that, so it decides. Reporting this as
            # "live" made sessions abandoned days ago trip the stall rule forever.
            "has_fragments": data.is_in_progress,
            "live": data.is_in_progress,
            "end_reason": data.end_reason,
            "minutes": round(data.duration_minutes, 1),
            "steps": self.step_count(),
            "game_date": game.get("game_date"),
            "mode": game.get("mode"),
            "map": f"{game.get('map_width', '?')}x{game.get('map_height', '?')}",
            "seed": data.settings.get("game_creation.generation_seed", ""),
            "rating": company.get("performance_rating"),
            "value": company.get("value"),
            "balance": company.get("money"),
            "stations": len(last.get("stations") or []),
            "vehicles": len(last.get("vehicles") or []),
            "actions": len(self._data.actions),
            "refused": self._refused_count(),
        }

    # ------------------------------------------------------------------
    # Series
    # ------------------------------------------------------------------

    def steps(self) -> list[dict[str, Any]]:
        """One row of scalars per snapshot, which is one row per step.

        ``step`` is the row's position rather than anything read from the game. The
        snapshot carries a game date and a tick, and neither is a step counter: a
        stepped session advances the date by a variable number of days per step.
        """
        rows: list[dict[str, Any]] = []
        actions_by_date = self._actions_by_date()
        # Banked fleet profit from years already closed. profit_this_year resets on 1 January
        # and a T1 run ENDS on 1 January, so the live sum reads near zero on the final
        # snapshot: measured 174,449 on 30-Dec-2020 and -20 the next step. Banking at the
        # year boundary keeps the cumulative series monotone.
        #
        # Banked on the game YEAR changing, not on the sum dropping. A crashed or sold vehicle
        # also drops the sum, and treating that as a year end would count its earnings twice.
        banked = 0
        previous_year: int | None = None
        previous_live = 0
        for index, snapshot in enumerate(self._snapshots()):
            game = snapshot.get("game") or {}
            company = self._company(snapshot)
            infra = self._infrastructure(snapshot)
            date = game.get("game_date")
            attempted, refused = actions_by_date.get(date, (0, 0))
            vehicles = snapshot.get("vehicles") or []
            live_profit = sum((v.get("profit_this_year") or 0) for v in vehicles)
            year = game_date_to_ymd(int(date))[0] if date is not None else None
            if previous_year is not None and year != previous_year:
                banked += previous_live
            previous_year, previous_live = year, live_profit
            row = {
                "step": index,
                "game_date": date,
                "balance": company.get("money"),
                "loan": company.get("loan"),
                "value": company.get("value"),
                "income": company.get("income"),
                # Live earnings. `income` is GetQuarterlyIncome, an accumulator that resets
                # at every quarter boundary, so the income chart is a sawtooth that says
                # nothing about the last few days. Each vehicle's profit_this_year updates
                # continuously and already nets its running cost, so the fleet total is the
                # honest answer to "is this company earning right now".
                "fleet_profit": live_profit,
                "fleet_profit_total": banked + live_profit,
                # What the fleet has been TOLD to do, and how many distinct services that is.
                # A vehicle with no orders is the failure a clone produces: it inherits the
                # order list but arrives stopped, so it sits in the depot earning nothing while
                # looking correctly configured.
                "orders_total": sum(len(v.get("orders") or []) for v in vehicles),
                "routes_distinct": _count_routes(vehicles),
                "vehicles_idle": sum(1 for v in vehicles if not (v.get("orders") or [])),
                "profit_last_year": company.get("profit_last_year"),
                "rating": company.get("performance_rating"),
                "stations": len(snapshot.get("stations") or []),
                "vehicles": len(snapshot.get("vehicles") or []),
                "cargo_waiting": self._cargo_waiting(snapshot),
                # What the company has actually carried, banked across the quarter resets
                # by the GameScript. Read against cargo_waiting on the same plot: waiting
                # climbing while delivered stays flat is a network that collects and does
                # not move, which is the failure mode a stalled fleet produces.
                "cargo_delivered": company.get("cargo_delivered_total"),
                "actions": attempted,
                "refused": refused,
            }
            for kind in INFRA_KINDS:
                row[f"{kind}_pieces"] = infra.get(f"{kind}_pieces", 0)
            counted = _count_station_kinds(snapshot.get("stations") or [])
            for kind in STATION_KINDS:
                row[f"stations_{kind}"] = counted.get(kind, 0)
            fleet = _count_vehicle_kinds(snapshot.get("vehicles") or [])
            for kind in VEHICLE_KINDS:
                row[f"vehicles_{kind}"] = fleet.get(kind, 0)
            rows.append(row)
        return rows

    def static_world(self) -> dict[str, Any]:
        """The parts of the world that are not the company's: towns and industries.

        Published once rather than per step. An industry can open or close mid-run, so
        this is the latest state rather than the first, which is the more useful of the
        two when looking at where a route should have gone.
        """
        last = self._latest()
        towns = [
            {"x": t.get("x"), "y": t.get("y"), "name": t.get("name"),
             "population": t.get("population")}
            for t in (last.get("towns") or [])
        ]
        industries = [
            {"x": i.get("x"), "y": i.get("y"), "name": i.get("name"),
             "type": i.get("type_name"), "raw": bool(i.get("is_raw"))}
            for i in (last.get("industries") or [])
        ]
        game = last.get("game") or {}
        return {
            "width": game.get("map_width") or 256,
            "height": game.get("map_height") or 256,
            "towns": towns,
            "industries": industries,
        }

    def dynamic_world(self) -> list[dict[str, Any]]:
        """What the company owns, per step, for the map scrubber."""
        frames: list[dict[str, Any]] = []
        for snapshot in self._snapshots():
            game = snapshot.get("game") or {}
            frames.append({
                "game_date": game.get("game_date"),
                "stations": [
                    {"x": s.get("x"), "y": s.get("y"), "name": s.get("name"),
                     "kind": _station_kind(s), "waiting": _waiting(s)}
                    for s in (snapshot.get("stations") or [])
                ],
                "vehicles": [
                    {"x": v.get("x"), "y": v.get("y"), "type": v.get("type")}
                    for v in (snapshot.get("vehicles") or [])
                ],
            })
        return frames

    def metrics(self) -> dict[str, Any]:
        """The scored business metrics, or empty while the run is still going.

        Read from result.parquet rather than recomputed, so the page shows the same numbers the
        leaderboard sorts on. They exist only once a session ends: the metrics are derived from
        the merged snapshot series, and that file is written when the recorder finalises.
        """
        result = self._data.result
        if result is None or result.is_empty():
            return {}
        return result.row(0, named=True)

    def tiles(self) -> Any:
        """The recorded terrain grid, for the map's base image.

        Empty for any session whose scan failed or predates it being captured, which the
        map handles by drawing the objects on a bare canvas.
        """
        return self._data.tiles

    def actions(self) -> list[dict[str, Any]]:
        """Every action submitted, newest first, with why it was refused."""
        frame = self._data.actions
        if frame.is_empty():
            return []
        wanted = [c for c in ("game_date", "action_type", "status", "error") if c in frame.columns]
        rows = frame.select(wanted).to_dicts()
        rows.reverse()
        return rows

    def fleet(self) -> list[dict[str, Any]]:
        """Every vehicle as it stands now, worst earner first.

        The table this feeds is the one thing the monitor could not answer while a run was
        going wrong. Every failure measured across eight hand-played runs was a SINGLE
        vehicle failing quietly: a train wandering the far corner of the map for 130 days,
        four aircraft parked in a hangar for sixty, ships circling the pool their depot sat
        in. From outside, all of it looked like a fleet of nine and a flat profit line.

        Sorted by profit ascending so the vehicle in trouble is the first row rather than
        somewhere in a list of thirty.
        """
        vehicles = self._latest().get("vehicles") or []
        rows = [
            {
                "id": v.get("id"),
                "type": v.get("type") or "",
                "profit": v.get("profit_this_year"),
                "orders": len(v.get("orders") or []) or v.get("order_count") or 0,
                "speed": v.get("current_speed"),
                "where": f"{v.get('x')},{v.get('y')}",
                "problem": _vehicle_problem(v),
            }
            for v in vehicles
        ]
        rows.sort(key=lambda r: (r["profit"] is None, r["profit"] or 0))
        return rows

    def action_types(self) -> list[dict[str, Any]]:
        """One row per action name: how many were submitted and how many were refused.

        The totals alone say 41 actions and 3 refused, which does not say whether one call
        failed three times or three calls failed once. A recipe that is refused every time
        is a different problem from an occasional refusal, and only the breakdown separates
        them.
        """
        counts: dict[str, list[int]] = {}
        for action in self.actions():
            name = action.get("action_type") or ""
            tally = counts.setdefault(name, [0, 0])
            tally[0] += 1
            if action.get("status") != "success":
                tally[1] += 1
        rows = [
            {"action": name, "total": total, "refused": bad,
             "rate": (total - bad) / total if total else 0.0}
            for name, (total, bad) in counts.items()
        ]
        # Most refused first: that is the row worth reading.
        rows.sort(key=lambda r: (-r["refused"], -r["total"]))
        return rows

    def events(self) -> list[dict[str, Any]]:
        """The game's own event timeline, newest first."""
        frame = self._data.events
        if frame.is_empty():
            return []
        wanted = [c for c in ("game_date", "event_type", "detail") if c in frame.columns]
        rows = frame.select(wanted).to_dicts()
        rows.reverse()
        return rows

    def action_mix(self) -> list[tuple[str, int, int]]:
        """Each action type tried, with how many succeeded and how many did not.

        The pair matters more than the total. Twenty two successful builds of one thing
        and nothing else is a different failure from twenty two refusals, and a single
        count cannot tell them apart.
        """
        frame = self._data.actions
        if frame.is_empty() or "action_type" not in frame.columns:
            return []
        counts: dict[str, list[int]] = {}
        for row in frame.select(["action_type", "status"]).to_dicts():
            name = row.get("action_type") or "?"
            tally = counts.setdefault(name, [0, 0])
            if row.get("status") == "success":
                tally[0] += 1
            else:
                tally[1] += 1
        ordered = sorted(counts.items(), key=lambda item: -(item[1][0] + item[1][1]))
        return [(name, ok, bad) for name, (ok, bad) in ordered]

    # ------------------------------------------------------------------

    def _snapshots(self) -> list[dict[str, Any]]:
        """Every snapshot as a dict, in capture order, parsed once per feed.

        A torn row is dropped rather than raising: this is read while another process is
        writing, and one unreadable fragment must not blank the whole page.
        """
        if self._parsed is not None:
            return self._parsed
        parsed: list[dict[str, Any]] = []
        for raw in self._raw_snapshots():
            decoded = _decode(raw)
            if decoded is not None:
                parsed.append(decoded)
        self._parsed = parsed
        return parsed

    def _latest(self) -> dict[str, Any]:
        """The newest readable snapshot, without parsing the ones before it."""
        if self._parsed is not None:
            return self._parsed[-1] if self._parsed else {}
        if self._last is not None:
            return self._last
        for raw in reversed(self._raw_snapshots()):
            decoded = _decode(raw)
            if decoded is not None:
                self._last = decoded
                return decoded
        self._last = {}
        return self._last

    def _raw_snapshots(self) -> list[str]:
        frame = self._data.snapshots
        if frame.is_empty() or "snapshot_json" not in frame.columns:
            return []
        return [raw for raw in frame["snapshot_json"].to_list() if raw]

    def step_count(self) -> int:
        """How many steps this session has, without decoding any of them.

        Rows, not parsed snapshots. Parsing to count cost a full JSON decode of every
        snapshot in every session listed, which is what made the index take over a second
        and a click during a live run feel unresponsive.

        A torn row is still excluded, because four places on the page show this number and
        they have to agree. A torn row is a half-written one, so it is recognised by shape
        rather than by parsing it: a complete snapshot is a JSON object and ends with its
        closing brace. That is a string comparison per row instead of a full decode, and it
        rejects the truncation that actually happens when a fragment is read mid-write.

        When the snapshots have been parsed anyway, for the charts and the scrubber, that
        count is authoritative and is used instead.
        """
        if self._parsed is not None:
            return len(self._parsed)
        return sum(1 for raw in self._raw_snapshots() if _looks_complete(raw))

    def _company(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """The contestant company. A session holds exactly one, so this is the first."""
        companies = snapshot.get("companies") or []
        return companies[0] if companies else {}

    def _infrastructure(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        entries = snapshot.get("infrastructure") or []
        return entries[0] if entries else {}

    def _cargo_waiting(self, snapshot: dict[str, Any]) -> int:
        """Cargo sitting at the company's stations, summed.

        Rising while vehicles stay flat is the clearest single sign of a route that
        collects more than it clears.
        """
        return sum(_waiting(s) for s in (snapshot.get("stations") or []))

    def _actions_by_date(self) -> dict[int, tuple[int, int]]:
        """Attempted and refused counts keyed by game date.

        Game date is the only key the two tables share. Several actions can land on one
        date, and a step that submitted nothing simply has no entry.
        """
        frame = self._data.actions
        if frame.is_empty() or "game_date" not in frame.columns:
            return {}
        tally: dict[int, tuple[int, int]] = {}
        for row in frame.select(["game_date", "status"]).to_dicts():
            date = row.get("game_date")
            attempted, refused = tally.get(date, (0, 0))
            failed = refused + (0 if row.get("status") == "success" else 1)
            tally[date] = (attempted + 1, failed)
        return tally

    def _refused_count(self) -> int:
        frame = self._data.actions
        if frame.is_empty() or "status" not in frame.columns:
            return 0
        return sum(1 for s in frame["status"].to_list() if s != "success")


def _vehicle_problem(vehicle: dict[str, Any]) -> str:
    """Why this vehicle is earning nothing, in the game's own words where it has them.

    lost and idle_reason come from the GameScript. They were reported by it and then
    dropped by the world model for months, so a lost vehicle arrived here indistinguishable
    from a working one; both are now carried through.
    """
    if vehicle.get("lost"):
        return "lost"
    reason = vehicle.get("idle_reason")
    if reason:
        return str(reason)
    if not (vehicle.get("orders") or vehicle.get("order_count")):
        return "no orders"
    if vehicle.get("in_depot"):
        return "in depot"
    if not vehicle.get("current_speed"):
        return "not moving"
    return ""


def _looks_complete(raw: str) -> bool:
    """Whether a snapshot row is a whole JSON object, without decoding it.

    Cheap stand-in for a parse, used only for counting. The failure it has to catch is a
    fragment read while it was being written, which truncates: the row then lacks its
    closing brace. Decoding every row to find those cost 0.7 seconds on an index of 34
    sessions.
    """
    text = raw.strip()
    return text.startswith("{") and text.endswith("}")


def _decode(raw: str) -> dict[str, Any] | None:
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _count_routes(vehicles: list[dict[str, Any]]) -> int:
    """How many distinct services the fleet runs.

    A route is the SET of stations a vehicle visits, so two vehicles sharing an order list
    are one route and not two. Counted from the order destinations rather than from vehicle
    count, because the useful question is how much of the map is served, and adding a third
    bus to one town pair does not serve any more of it.
    """
    seen = set()
    for vehicle in vehicles:
        stops = frozenset(
            o.get("destination") for o in (vehicle.get("orders") or [])
            if o.get("is_goto_station")
        )
        if len(stops) > 1:
            seen.add(stops)
    return len(seen)


def _count_vehicle_kinds(vehicles: list[dict[str, Any]]) -> dict[str, int]:
    """How many of each vehicle type the company owns, by the snapshot's own `type` field."""
    tally: dict[str, int] = {}
    for vehicle in vehicles:
        kind = str(vehicle.get("type") or "other")
        tally[kind] = tally.get(kind, 0) + 1
    return tally


def _count_station_kinds(stations: list[dict[str, Any]]) -> dict[str, int]:
    """How many of each station-like thing the company owns.

    Counted by the same first-match rule the map markers use, so the chart and the map never
    disagree about what a station is.
    """
    tally: dict[str, int] = {}
    for station in stations:
        kind = _station_kind(station)
        tally[kind] = tally.get(kind, 0) + 1
    return tally


def _station_kind(station: dict[str, Any]) -> str:
    """Which transport a station serves, for its marker shape.

    A station can serve more than one, so the first match wins and the order is the one
    a reader cares about: the heavier infrastructure is the more informative label.
    """
    if station.get("has_airport"):
        return "air"
    if station.get("has_dock"):
        return "dock"
    if station.get("has_rail"):
        return "rail"
    if station.get("has_truck"):
        return "truck"
    if station.get("has_bus"):
        return "bus"
    return "other"


def _waiting(station: dict[str, Any]) -> int:
    return sum(int(c.get("waiting") or 0) for c in (station.get("cargo_waiting") or []))
