"""The map focus: resolving places, clipping snapshots, and the outside index."""

from __future__ import annotations

from typing import Any

from nttd.mcp.focus import FocusRegistry, clip_snapshot, coerce_names, tile_xy

WIDTH = 64


def tile(x: int, y: int) -> int:
    return y * WIDTH + x


def snapshot() -> dict[str, Any]:
    return {
        "game": {"map_width": WIDTH, "map_height": WIDTH},
        "companies": [{"id": 0, "money": 1000, "loan": 0}],
        "towns": [
            {"id": 1, "name": "Weston", "x": 10, "y": 10},
            {"id": 2, "name": "Easton", "x": 50, "y": 50},
        ],
        "industries": [
            {"id": 7, "name": "Weston Coal Mine", "type_name": "Coal Mine", "x": 14, "y": 8},
            {"id": 8, "name": "Easton Power Station", "type_name": "Power Station", "x": 52, "y": 55},
        ],
        "stations": [
            {"id": 100, "name": "Weston Mine", "x": 15, "y": 9},
            {"id": 200, "name": "Easton PS", "x": 51, "y": 54},
        ],
        "vehicles": [
            {"id": 1, "x": 12, "y": 10, "orders": [{"destination": tile(15, 9)}]},
            {"id": 2, "x": 40, "y": 40,
             "orders": [{"destination": tile(15, 9)}, {"destination": tile(51, 54)}]},
            {"id": 3, "x": 50, "y": 52, "orders": [{"destination": tile(51, 54)}]},
        ],
        "routes": [
            {"route_id": "west-east", "station_ids": [100, 200], "vehicle_ids": [2]},
            {"route_id": "east", "station_ids": [200], "vehicle_ids": [3]},
        ],
    }


WEST = {"x1": 5, "y1": 3, "x2": 19, "y2": 15}


def test_coerce_names_accepts_lists_scalars_and_strings() -> None:
    assert coerce_names(["Weston", 7]) == ["Weston", "7"]
    assert coerce_names("Weston, Easton") == ["Weston", "Easton"]
    assert coerce_names('["Weston"]') == ["Weston"]
    assert coerce_names(7) == ["7"]
    assert coerce_names(None) == []
    assert coerce_names("  ") == []


def test_tile_xy_decodes_row_major_tiles() -> None:
    assert tile_xy(tile(15, 9), WIDTH) == (15, 9)


def test_focus_around_named_places_is_padded_and_recorded() -> None:
    registry = FocusRegistry()
    outcome = registry.set_focus("a", snapshot(), {"towns": ["weston"], "industries": "7", "padding": 5})
    focus = outcome["focus"]
    assert {k: focus[k] for k in WEST} == WEST
    assert focus["padding"] == 5
    assert [(a["kind"], a["id"]) for a in focus["anchors"]] == [("town", 1), ("industry", 7)]


def test_focus_rectangle_is_clamped_and_merged_with_places() -> None:
    registry = FocusRegistry()
    rect_only = registry.set_focus("a", snapshot(), {"x1": -4, "y1": 99, "x2": 99, "y2": 40})["focus"]
    assert {k: rect_only[k] for k in WEST} == {"x1": 0, "y1": 40, "x2": WIDTH - 1, "y2": WIDTH - 1}
    merged = registry.set_focus("a", snapshot(), {"x1": 0, "y1": 0, "x2": 2, "y2": 2, "towns": ["Easton"], "padding": 0})["focus"]
    assert {k: merged[k] for k in WEST} == {"x1": 0, "y1": 0, "x2": 50, "y2": 50}


def test_focus_reports_unknown_places_and_empty_requests() -> None:
    registry = FocusRegistry()
    assert registry.set_focus("a", snapshot(), {"towns": ["Nowhere"]}) == {"error": "Unknown town or industry: Nowhere"}
    assert "error" in registry.set_focus("a", snapshot(), {})
    assert registry.get("a") is None


def test_clip_keeps_entities_inside_vehicles_by_order_and_routes_by_station() -> None:
    clipped, hidden = clip_snapshot(snapshot(), WEST)
    assert [t["name"] for t in clipped["towns"]] == ["Weston"]
    assert [i["id"] for i in clipped["industries"]] == [7]
    assert [s["id"] for s in clipped["stations"]] == [100]
    assert [v["id"] for v in clipped["vehicles"]] == [1, 2]
    assert [r["route_id"] for r in clipped["routes"]] == ["west-east"]
    assert clipped["companies"] == snapshot()["companies"]
    assert hidden == {"towns": 1, "industries": 1, "stations": 1, "vehicles": 1, "routes": 1}


def test_apply_cuts_step_snapshot_but_not_action_results_and_indexes_outside() -> None:
    registry = FocusRegistry()
    registry.set_focus("a", snapshot(), {"towns": ["Weston"], "industries": ["7"], "padding": 5})
    registry.set_focus("b", snapshot(), {"towns": ["Easton"], "padding": 10})
    registry.set_focus("c", snapshot(), {"x1": 0, "y1": 0, "x2": 60, "y2": 60})
    result = {"snapshot": snapshot(), "action_results": [{"status": "success", "x": 55, "y": 55}], "reward": 1.0}
    view = registry.apply("a", result)
    assert [t["name"] for t in view["snapshot"]["towns"]] == ["Weston"]
    assert view["action_results"] == result["action_results"]
    assert view["reward"] == 1.0
    assert view["focus"]["anchors"][1]["name"] == "Weston Coal Mine"
    assert view["focus"]["overlapping"] == ["c"]
    assert view["outside"]["counts"] == {"towns": 1, "industries": 1, "stations": 1, "vehicles": 1, "routes": 1}
    outside = {(e["kind"], e["name"]): e for e in view["outside"]["places"]}
    assert set(outside) == {("town", "Easton"), ("industry", "Easton Power Station")}
    assert outside[("town", "Easton")]["y"] == 50
    assert outside[("industry", "Easton Power Station")]["type"] == "Power Station"
    assert outside[("industry", "Easton Power Station")]["x"] == 52


def test_apply_cuts_observe_results_and_passes_through_without_focus() -> None:
    registry = FocusRegistry()
    observed = {**snapshot(), "step": 3}
    assert registry.apply("nobody", observed) is observed
    assert registry.apply("nobody", {"queried": "get_date"}) == {"queried": "get_date"}
    registry.set_focus("a", snapshot(), {"towns": ["Weston"], "padding": 9})
    view = registry.apply("a", observed)
    assert view["step"] == 3
    assert [t["name"] for t in view["towns"]] == ["Weston"]
    assert "outside" in view
    assert registry.apply("a", {"queried": "get_date"}) == {"queried": "get_date"}


def test_clearing_a_focus_restores_the_whole_map() -> None:
    registry = FocusRegistry()
    registry.set_focus("a", snapshot(), {"towns": ["Weston"], "padding": 9})
    registry.clear("a")
    assert registry.get("a") is None
    assert len(registry.apply("a", snapshot())["towns"]) == 2
