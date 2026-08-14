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

from nttd.analysis.loader import SessionData

# The infrastructure kinds a company can own, in the order they are charted. Named here
# rather than discovered from the data so a mode that built none of something still gets
# a labelled zero series instead of vanishing from the legend.
INFRA_KINDS = ("rail", "road", "water", "station", "airport")


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
            "session_name": data.name or data.session_id,
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
            "steps": self._snapshot_count(),
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
        for index, snapshot in enumerate(self._snapshots()):
            game = snapshot.get("game") or {}
            company = self._company(snapshot)
            infra = self._infrastructure(snapshot)
            date = game.get("game_date")
            attempted, refused = actions_by_date.get(date, (0, 0))
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
                "fleet_profit": sum(
                    (v.get("profit_this_year") or 0) for v in (snapshot.get("vehicles") or [])
                ),
                "profit_last_year": company.get("profit_last_year"),
                "rating": company.get("performance_rating"),
                "stations": len(snapshot.get("stations") or []),
                "vehicles": len(snapshot.get("vehicles") or []),
                "cargo_waiting": self._cargo_waiting(snapshot),
                "actions": attempted,
                "refused": refused,
            }
            for kind in INFRA_KINDS:
                row[f"{kind}_pieces"] = infra.get(f"{kind}_pieces", 0)
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

    def _snapshot_count(self) -> int:
        """How many steps this session has, counted ONCE for the whole page.

        Counts parsed snapshots, not raw rows. The two differ when a fragment is torn, which
        happens while another process is writing, and the map scrubber has always built its
        frames from the parsed list. Counting raw rows here made the sidebar, the cards and
        the index table disagree with the scrubber by however many rows were unreadable.
        """
        return len(self._snapshots())

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


def _decode(raw: str) -> dict[str, Any] | None:
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


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
