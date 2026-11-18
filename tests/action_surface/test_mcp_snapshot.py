"""The reshaping the server applies to game replies before an agent reads them."""

from __future__ import annotations

from nttd.mcp.snapshot import TIMEOUT_NOTE, explain_timeouts, rename_income, reshape, with_vehicle_state_words


def test_every_vehicle_carries_its_state_as_a_word() -> None:
    """The fleet list carries a state code, a speed, a running flag that repeats the
    code, an idle_reason that is always empty and a lost flag that is always false.
    The code becomes the word the game uses for one vehicle, "no_path" comes from the
    route check, and the three fields that add nothing or contradict are dropped."""
    snapshot = {
        "vehicles": [
            {"id": 1, "state": 0, "current_speed": 30, "running": True, "idle_reason": "", "lost": False},
            {"id": 2, "state": 1, "current_speed": 0, "running": False, "idle_reason": "", "lost": False},
            {"id": 3, "state": 2, "current_speed": 0},
            {"id": 4, "state": 3, "current_speed": 0},
            {"id": 5, "state": 4, "current_speed": 0},
            {"id": 6, "state": 5, "current_speed": 0},
            {"id": 7, "state": 0, "current_speed": 0},
            {"id": 8, "state": 0, "current_speed": 24},
        ],
        "routes": [{"route_id": "rt_1", "vehicle_ids": [7, 8], "vehicles_without_path": [8]}],
        "companies": [],
    }

    out = with_vehicle_state_words(snapshot)

    assert [v["state"] for v in out["vehicles"]] == [
        "running",
        "stopped",
        "in_depot",
        "at_station",
        "broken_down",
        "crashed",
        "halted",
        "no_path",
    ]
    assert out["vehicles"][0] == {"id": 1, "state": "running", "current_speed": 30}
    assert snapshot["vehicles"][0]["state"] == 0


def test_income_is_named_for_the_quarter_it_reports() -> None:
    snapshot = {"companies": [{"id": 0, "money": 10, "income": 7}, "odd"], "towns": []}
    out = rename_income(snapshot)
    assert out["companies"][0] == {"id": 0, "money": 10, "revenue_last_quarter": 7}
    assert out["companies"][1] == "odd"
    assert "income" in snapshot["companies"][0]


def test_reshape_applies_both_changes_and_leaves_other_replies_alone() -> None:
    snapshot = {"companies": [{"income": 1}], "vehicles": [{"id": 1, "state": 1}], "routes": []}
    out = reshape(snapshot)
    assert out["companies"][0] == {"revenue_last_quarter": 1}
    assert out["vehicles"][0] == {"id": 1, "state": "stopped"}
    assert reshape({"queried": "get_date"}) == {"queried": "get_date"}


def test_a_search_timeout_is_explained() -> None:
    results = [
        {
            "status": "failed",
            "error": ("the game did not answer within 120s and the stream was healthy, "
                      "so the command was slow rather than lost"),
        },
        {"status": "success", "error": None},
        "not a dict",
    ]
    explained = explain_timeouts(results)
    assert explained[0]["error"].endswith(TIMEOUT_NOTE)
    assert explained[1] == results[1]
    assert explained[2] == "not a dict"
