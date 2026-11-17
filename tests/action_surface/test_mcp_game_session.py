"""The game session: mode, rounds, ids, reward, focus and the end of the game.

The game is a fake HTTP server, so these run without OpenTTD.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from nttd.api.participant_auth import TOKEN_HEADER
from nttd.mcp.game_session import GAME_ENDED_NOTE, MISSING_RESULT_NOTE, GameSession
from nttd.mcp.participant_client import ParticipantClient

BASE = "/v1/participant/sessions/ses_test"


def snapshot(money: int = 1000, loan: int = 0) -> dict[str, Any]:
    return {
        "game": {"map_width": 64, "map_height": 64},
        "companies": [{"id": 0, "money": money, "loan": loan, "income": 5}],
        "towns": [{"id": 1, "name": "Weston", "x": 10, "y": 10}, {"id": 2, "name": "Easton", "x": 50, "y": 50}],
        "industries": [], "stations": [],
        "vehicles": [{"id": 1, "state": 1, "current_speed": 0, "x": 10, "y": 10}],
        "routes": [],
    }


class FakeGame:
    """Answers the participant routes and records every request."""

    def __init__(self, mode: str = "stepped", money: int = 1000, terminated: bool = False, closed: bool = False) -> None:
        self.mode = mode
        self.money = money
        self.terminated = terminated
        self.closed = closed
        self.seen: list[tuple[str, str, Any]] = []
        self.step_number = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.seen.append((request.method, request.url.path, body))
        path = request.url.path
        if path.endswith("/status"):
            return httpx.Response(200, json={"mode": self.mode})
        if self.closed:
            return httpx.Response(404, json={"detail": "no such session"})
        if path.endswith("/step/reset"):
            return httpx.Response(200, json={"snapshot": snapshot(self.money), "step": 0, "days_advanced": 0})
        if path.endswith("/step"):
            self.step_number += 1
            results = [
                {"action_id": entry["action_id"], "action_type": entry["action"], "status": "success"}
                for entry in reversed(body["actions"])
            ]
            return httpx.Response(200, json={
                "snapshot": snapshot(self.money), "step": self.step_number, "days_advanced": 1,
                "terminated": self.terminated, "end_reason": "horizon" if self.terminated else None,
                "action_results": results,
            })
        if path.endswith("/actions/submit-batch"):
            return httpx.Response(200, json=[
                {"action_id": env["action_id"], "action_type": env["action_type"], "status": "failed", "error": "x"}
                for env in body
            ])
        if path.endswith("/state/full"):
            return httpx.Response(200, json=snapshot(self.money))
        if path.endswith("/state/gs/query"):
            return httpx.Response(200, json={"queried": request.url.params["action"], "params": body})
        if path.endswith("/interpret/validate"):
            return httpx.Response(200, json={"total": len(body), "valid": len(body), "invalid": 0, "results": []})
        return httpx.Response(500, json={"detail": f"unexpected {path}"})

    def calls(self, suffix: str) -> list[tuple[str, str, Any]]:
        return [call for call in self.seen if call[1].endswith(suffix)]


def session(game: FakeGame, **kwargs: Any) -> GameSession:
    client = ParticipantClient("http://nttd.test", "ses_test")
    client._http = httpx.AsyncClient(base_url="http://nttd.test", transport=httpx.MockTransport(game.handle))
    return GameSession(client, **kwargs)


def moves(*commands: str) -> list[dict[str, Any]]:
    return [{"command": command, "parameters": {"n": index}} for index, command in enumerate(commands)]


# ---- the client -----------------------------------------------------------------

def test_the_client_sends_no_token_header_when_it_has_none() -> None:
    game = FakeGame()
    client = ParticipantClient("http://nttd.test", "ses_test")
    client._http = httpx.AsyncClient(base_url="http://nttd.test", transport=httpx.MockTransport(game.handle), headers=client._http.headers)
    asyncio.run(client.observe())
    assert TOKEN_HEADER not in client._http.headers


def test_the_client_reaches_reset_and_submit_batch() -> None:
    game = FakeGame()
    client = ParticipantClient("http://nttd.test", "ses_test")
    client._http = httpx.AsyncClient(base_url="http://nttd.test", transport=httpx.MockTransport(game.handle))
    asyncio.run(client.reset())
    asyncio.run(client.submit_batch([{"action_id": "a:0", "company_id": 0, "action_type": "ping", "parameters": {}, "mode": "atomic"}]))
    assert [call[1] for call in game.seen] == [f"{BASE}/step/reset", f"{BASE}/actions/submit-batch"]


# ---- start -----------------------------------------------------------------------

def test_a_stepped_session_registers_once_at_start_and_takes_its_baseline() -> None:
    game = FakeGame(mode="stepped", money=700)
    played = session(game)
    opening = asyncio.run(played.start())
    assert played.mode == "stepped"
    assert len(game.calls("/step/reset")) == 1
    assert played.last_net_worth == 700.0
    assert opening["companies"][0]["revenue_last_quarter"] == 5


def test_a_clocked_session_never_registers_and_reads_one_snapshot() -> None:
    game = FakeGame(mode="heartbeat", money=300)
    played = session(game)
    asyncio.run(played.start())
    assert played.mode == "heartbeat"
    assert game.calls("/step/reset") == []
    assert len(game.calls("/state/full")) == 1
    assert played.last_net_worth == 300.0


# ---- rounds ----------------------------------------------------------------------

def test_a_stepped_round_is_one_step_with_named_commands() -> None:
    game = FakeGame(mode="stepped")
    played = session(game, seed=1)
    asyncio.run(played.start())
    results = asyncio.run(played.play_round({"a": moves("set_loan", "ping"), "b": moves("build_dock")}))

    (_, _, body), = game.calls("/step")
    sent = body["actions"]
    assert {entry["action_id"] for entry in sent} == {"a:0", "a:1", "b:2"} or {entry["action_id"] for entry in sent} == {"b:0", "a:1", "a:2"}
    assert all(entry["params"]["company_id"] == 0 for entry in sent)
    assert all(entry["metadata"]["participant_id"] == entry["action_id"].split(":")[0] for entry in sent)
    assert "days" not in body

    assert [r["action_type"] for r in results["a"]["action_results"]] == ["set_loan", "ping"]
    assert [r["action_type"] for r in results["b"]["action_results"]] == ["build_dock"]
    assert results["a"]["step"] == 1 and results["a"]["days_advanced"] == 1
    assert results["a"]["snapshot"]["vehicles"][0]["state"] == "stopped"
    assert "reward" not in results["a"]
    assert played.step_count == 1


def test_results_pair_by_id_even_when_the_game_reorders_them() -> None:
    """The fake game answers in reverse order on purpose."""
    game = FakeGame(mode="stepped")
    played = session(game, seed=3)
    asyncio.run(played.start())
    results = asyncio.run(played.play_round({"a": moves("set_loan", "ping", "build_dock")}))
    own = results["a"]["action_results"]
    assert [r["action_type"] for r in own] == ["set_loan", "ping", "build_dock"]
    assert [r["action_id"] for r in own] == ["a:0", "a:1", "a:2"]


def test_the_actor_order_is_random_but_seeded() -> None:
    orders = []
    for _ in range(2):
        game = FakeGame(mode="stepped")
        played = session(game, seed=7)
        asyncio.run(played.start())
        asyncio.run(played.play_round({tag: moves("ping") for tag in "abcdef"}))
        (_, _, body), = game.calls("/step")
        orders.append([entry["metadata"]["participant_id"] for entry in body["actions"]])
    assert orders[0] == orders[1]
    assert orders[0] != list("abcdef")


def test_the_step_size_flag_is_sent_with_every_step() -> None:
    game = FakeGame(mode="stepped")
    played = session(game, days=3)
    asyncio.run(played.start())
    asyncio.run(played.play_round({"a": []}))
    (_, _, body), = game.calls("/step")
    assert body == {"actions": [], "days": 3}


def test_a_clocked_round_submits_one_batch_per_actor_then_observes() -> None:
    game = FakeGame(mode="heartbeat")
    played = session(game, seed=1)
    asyncio.run(played.start())
    results = asyncio.run(played.play_round({"a": moves("set_loan"), "b": moves("ping", "build_dock")}))
    batches = game.calls("/actions/submit-batch")
    assert len(batches) == 2
    envelopes = [env for _, _, body in batches for env in body]
    assert all(env["company_id"] == 0 and env["mode"] == "atomic" for env in envelopes)
    assert all(env["metadata"]["participant_id"] == env["action_id"].split(":")[0] for env in envelopes)
    assert game.calls("/step") == []
    assert game.seen[-1][1] == f"{BASE}/state/full"
    assert [r["status"] for r in results["b"]["action_results"]] == ["failed", "failed"]
    assert results["a"]["step"] == 1 and "days_advanced" not in results["a"]


def test_a_command_the_game_did_not_answer_gets_a_placeholder() -> None:
    game = FakeGame(mode="stepped")
    played = session(game)
    asyncio.run(played.start())
    played.client.step = lambda actions, days: _answer({"snapshot": snapshot(), "step": 1, "action_results": []})  # type: ignore[method-assign]
    results = asyncio.run(played.play_round({"a": moves("ping")}))
    placeholder = results["a"]["action_results"][0]
    assert placeholder["status"] == "unknown" and placeholder["error"] == MISSING_RESULT_NOTE
    assert placeholder["action_id"] == "a:0"


async def _answer(value: Any) -> Any:
    return value


# ---- reward ----------------------------------------------------------------------

def test_the_reward_is_the_whole_change_in_net_worth_for_every_actor() -> None:
    game = FakeGame(mode="stepped", money=1000)
    played = session(game, reward_enabled=True)
    asyncio.run(played.start())
    game.money = 1250
    results = asyncio.run(played.play_round({"a": moves("ping"), "b": moves("ping")}))
    assert results["a"]["reward"] == 250.0 and results["b"]["reward"] == 250.0
    game.money = 1200
    results = asyncio.run(played.play_round({"a": moves("ping")}))
    assert results["a"]["reward"] == -50.0


def test_the_baseline_moves_even_when_the_reward_is_off() -> None:
    game = FakeGame(mode="stepped", money=1000)
    played = session(game)
    asyncio.run(played.start())
    game.money = 1250
    asyncio.run(played.play_round({"a": moves("ping")}))
    assert played.last_net_worth == 1250.0


# ---- end of the game -------------------------------------------------------------

def test_after_the_game_ends_every_round_returns_the_ended_result() -> None:
    game = FakeGame(mode="stepped", terminated=True)
    played = session(game)
    asyncio.run(played.start())
    results = asyncio.run(played.play_round({"a": moves("ping")}))
    assert results["a"]["terminated"] is True and results["a"]["end_reason"] == "horizon"
    later = asyncio.run(played.play_round({"a": moves("ping"), "b": []}))
    assert later["a"] == {"terminated": True, "end_reason": "horizon", "note": GAME_ENDED_NOTE}
    assert later["b"] == later["a"]
    assert len(game.calls("/step")) == 1


def test_a_closed_clocked_session_is_the_end_of_the_game() -> None:
    game = FakeGame(mode="heartbeat")
    played = session(game)
    asyncio.run(played.start())
    game.closed = True
    results = asyncio.run(played.play_round({"a": moves("ping")}))
    assert results["a"]["note"] == GAME_ENDED_NOTE and results["a"]["end_reason"] == "session closed"
    assert played.terminated


# ---- lookups, validation, focus --------------------------------------------------

def test_operator_actions_are_unknown_to_the_lookup() -> None:
    played = session(FakeGame())
    listing = played.lookup_action(None)
    assert listing["count"] == 124
    assert "change_bank_balance" not in listing["commands"]
    assert "build_rail_station" in listing["commands"] and "get_towns" in listing["commands"]
    refused = played.lookup_action("change_bank_balance")
    assert refused["error"].startswith("No such command")
    assert played.lookup_action("build_rail_station")["tier"] == "participant"
    assert "build_rail_station" in played.lookup_action("build_rail_statoin")["did_you_mean"]


def test_validate_sends_the_game_shape_and_marks_the_reply_as_a_dry_run() -> None:
    game = FakeGame()
    played = session(game)
    reply = asyncio.run(played.validate(moves("set_loan")))
    (_, _, body), = game.calls("/interpret/validate")
    assert body == [{"action_type": "set_loan", "parameters": {"n": 0}}]
    assert reply["dry_run"] is True and reply["valid"] == 1


def test_a_query_reaches_the_game_with_its_parameters() -> None:
    game = FakeGame()
    played = session(game)
    reply = asyncio.run(played.query("get_town_info", {"town_id": 3}))
    assert reply == {"queried": "get_town_info", "params": {"town_id": 3}}


def test_focus_cuts_this_agents_views_only() -> None:
    game = FakeGame(mode="stepped")
    played = session(game, seed=1)
    asyncio.run(played.start())
    view = asyncio.run(played.set_focus("a", {"towns": ["Weston"], "padding": 5}))
    assert [t["name"] for t in view["towns"]] == ["Weston"]
    assert view["outside"]["counts"]["towns"] == 1
    assert len(asyncio.run(played.observe("b"))["towns"]) == 2
    results = asyncio.run(played.play_round({"a": moves("ping"), "b": moves("ping")}))
    assert len(results["a"]["snapshot"]["towns"]) == 2, "a round result is raw until view() cuts it"
    assert len(played.view("a", results["a"])["snapshot"]["towns"]) == 1
    assert len(played.view("b", results["b"])["snapshot"]["towns"]) == 2
    assert played.last_snapshot is not None and len(played.last_snapshot["towns"]) == 2
    whole = asyncio.run(played.clear_focus("a"))
    assert len(whole["towns"]) == 2 and "focus" not in whole
    assert asyncio.run(played.set_focus("a", {"towns": ["Nowhere"]})) == {"error": "Unknown town or industry: Nowhere"}


def test_the_default_tag_names_a_caller_that_gave_none() -> None:
    played = session(FakeGame(), default_tag="solo")
    assert played.tag(None) == "solo" and played.tag("  ") == "solo" and played.tag(" crew_1 ") == "crew_1"


def test_ensure_started_starts_once() -> None:
    game = FakeGame(mode="stepped")
    played = session(game)
    asyncio.run(played.ensure_started())
    asyncio.run(played.ensure_started())
    assert len(game.calls("/status")) == 1 and len(game.calls("/step/reset")) == 1
