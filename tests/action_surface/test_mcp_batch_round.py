"""The tools and the round envelope, against a fake HTTP game."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from nttd.mcp.game_session import GAME_ENDED_NOTE, GameSession
from nttd.mcp.moves import MOVES_FORMAT_HINT
from nttd.mcp.participant_client import ParticipantClient
from nttd.mcp.server import build
from nttd.mcp.tools.batch_round import run_round
from nttd.mcp.tools.query import PARAMETERS_FORMAT_HINT
from tests.action_surface.test_mcp_game_session import FakeGame


def session_for(game: FakeGame, **kwargs: Any) -> GameSession:
    client = ParticipantClient("http://nttd.test", "ses_test")
    client._http = httpx.AsyncClient(base_url="http://nttd.test", transport=httpx.MockTransport(game.handle))
    played = GameSession(client, **kwargs)
    played.mode = game.mode
    return played


def served(game: FakeGame, **kwargs: Any) -> tuple[Any, GameSession]:
    """A built server whose session talks to the fake game."""
    mcp = build("http://nttd.test", "ses_test", None, "127.0.0.1", 8100, mode=game.mode, **kwargs)
    bound = _session_of(mcp)
    bound.client = session_for(game).client
    return mcp, bound


def _session_of(mcp: Any) -> GameSession:
    for tool in mcp._tool_manager._tools.values():
        for cell in tool.fn.__closure__ or ():
            if isinstance(cell.cell_contents, GameSession):
                return cell.cell_contents
    raise AssertionError("no session bound to the tools")


def call(mcp: Any, name: str, **kwargs: Any) -> Any:
    result = asyncio.run(mcp.call_tool(name, kwargs))
    payload = result[1] if isinstance(result, tuple) else result
    if isinstance(payload, dict) and "result" in payload:
        return json.loads(payload["result"])
    return json.loads(payload[0].text)


# ---- the single-agent tools ----------------------------------------------------------


def test_act_plays_one_round_for_the_caller_and_starts_the_session_first() -> None:
    game = FakeGame(mode="stepped")
    mcp, played = served(game)
    reply = call(mcp, "act", moves=[{"command": "set_loan", "parameters": {"amount": 5}}])
    assert len(game.calls("/step/reset")) == 1
    ((_, _, body),) = game.calls("/step")
    assert body["actions"][0]["action_id"] == "agent:0"
    assert body["actions"][0]["metadata"] == {"participant_id": "agent"}
    assert reply["action_results"][0]["action_type"] == "set_loan"
    assert reply["snapshot"]["companies"][0]["revenue_last_quarter"] == 5


def test_act_takes_the_agent_tag_when_given() -> None:
    game = FakeGame(mode="stepped")
    mcp, _ = served(game)
    call(mcp, "act", moves=[{"command": "set_loan", "parameters": {"amount": 5}}], agent_tag="crew_2")
    ((_, _, body),) = game.calls("/step")
    assert body["actions"][0]["action_id"] == "crew_2:0"


def test_act_with_dry_run_only_validates() -> None:
    game = FakeGame(mode="stepped")
    mcp, _ = served(game)
    reply = call(mcp, "act", moves=[{"command": "set_loan", "parameters": {"amount": 5}}], dry_run=True)
    assert reply["dry_run"] is True and reply["valid"] == 1
    assert game.calls("/step") == []


def test_act_with_no_moves_passes_the_day_in_stepped_mode() -> None:
    game = FakeGame(mode="stepped")
    mcp, _ = served(game)
    reply = call(mcp, "act")
    ((_, _, body),) = game.calls("/step")
    assert body["actions"] == [] and reply["action_results"] == []


def test_observe_query_and_focus_work_through_the_tools() -> None:
    game = FakeGame(mode="heartbeat")
    mcp, _ = served(game)
    whole = call(mcp, "observe")
    assert len(whole["towns"]) == 2 and whole["vehicles"][0]["state"] == "stopped"
    focused = call(mcp, "focus", towns=["Weston"], padding=5, agent_tag="a")
    assert [t["name"] for t in focused["towns"]] == ["Weston"]
    assert len(call(mcp, "observe", agent_tag="a")["towns"]) == 1
    assert len(call(mcp, "observe", agent_tag="b")["towns"]) == 2
    cleared = call(mcp, "focus", clear=True, agent_tag="a")
    assert len(cleared["towns"]) == 2
    queried = call(mcp, "query", query="get_town_info", parameters={"town_id": 1})
    assert queried == {"queried": "get_town_info", "params": {"town_id": 1}}


# ---- the round envelope ----------------------------------------------------------------


def entry(tag: str, tool: str, **args: Any) -> dict[str, Any]:
    return {"agent_tag": tag, "tool": tool, "args": args}


def test_a_round_runs_reads_then_one_step_and_answers_every_agent() -> None:
    game = FakeGame(mode="stepped")
    played = session_for(game, seed=1)
    asyncio.run(played.start())
    reply = asyncio.run(
        run_round(
            played,
            [
                entry("a", "act", moves=[{"command": "set_loan", "parameters": {"amount": 5}}, {"command": "ping"}]),
                entry("b", "act", moves=[{"command": "build_dock"}]),
                entry("c", "observe"),
                entry("d", "query", query="get_date", parameters={}),
                entry("e", "list_commands", name="ping"),
                entry("f", "act", moves=[{"command": "ping"}], dry_run="true"),
                entry("g", "act", moves="not json"),
                entry("h", "nothing"),
            ],
        )
    )["results"]
    assert len(game.calls("/step")) == 1 and game.calls("/state/full") == []
    assert [r["action_type"] for r in reply["a"]["action_results"]] == ["set_loan", "ping"]
    assert [r["action_type"] for r in reply["b"]["action_results"]] == ["build_dock"]
    assert len(reply["c"]["towns"]) == 2 and "action_results" not in reply["c"]
    assert reply["d"]["queried"] == "get_date"
    assert reply["e"]["name"] == "ping"
    assert reply["f"]["dry_run"] is True
    assert reply["g"] == {"error": MOVES_FORMAT_HINT}
    assert reply["h"] == {"error": "Unknown tool: nothing"}


def test_daemon_and_creator_share_context_and_reward_but_keep_separate_results() -> None:
    game = FakeGame(mode="stepped")
    mcp, played = served(game, reward=True)
    asyncio.run(played.start())
    played.focus.set_focus("alice", played.last_snapshot or {}, {"towns": ["Weston"], "padding": 5})
    game.money += 100
    reply = call(mcp, "batch_round", entries=[
        entry("alice", "act", moves=[{"command": "ping"}]),
        {**entry("daemon:act", "act", moves=[{"command": "set_loan", "parameters": {"amount": 5}}]), "owner_tag": "alice"},
        {**entry("daemon:observe", "observe"), "owner_tag": "alice"},
    ])["results"]

    assert set(reply) == {"alice", "daemon:act", "daemon:observe"}
    ((_, _, body),) = game.calls("/step")
    assert len(body["actions"]) == 2
    assert all(action["metadata"]["participant_id"] == "alice" for action in body["actions"])
    assert reply["alice"]["action_results"][0]["action_type"] == "ping"
    assert reply["daemon:act"]["action_results"][0]["action_type"] == "set_loan"
    for tag in ("alice", "daemon:act"):
        assert [town["name"] for town in reply[tag]["snapshot"]["towns"]] == ["Weston"]
    assert [town["name"] for town in reply["daemon:observe"]["towns"]] == ["Weston"]
    assert [result["reward"] for result in reply.values() if "reward" in result] == [100.0]
    batch_tool = next(tool for tool in asyncio.run(mcp.list_tools()) if tool.name == "batch_round")
    assert batch_tool.meta == {"terralingua/owner_tag": True}


def test_a_round_sets_focus_and_returns_the_focused_view_with_one_fetch() -> None:
    game = FakeGame(mode="stepped")
    played = session_for(game, seed=1)
    asyncio.run(played.start())
    game.seen.clear()
    reply = asyncio.run(
        run_round(
            played,
            [
                entry("a", "focus", towns="Weston", padding="9"),
                entry("b", "focus", towns=["Easton"]),
                entry("c", "observe"),
                entry("d", "focus", towns=["Nowhere"]),
            ],
        )
    )["results"]
    assert len(game.calls("/state/full")) == 1
    assert [t["name"] for t in reply["a"]["towns"]] == ["Weston"]
    assert reply["a"]["focus"]["anchors"][0]["name"] == "Weston"
    assert [t["name"] for t in reply["b"]["towns"]] == ["Easton"]
    assert len(reply["c"]["towns"]) == 2
    assert reply["d"] == {"error": "Unknown town or industry: Nowhere"}
    assert played.focus.get("d") is None


def test_a_round_clears_focus_and_returns_the_whole_map() -> None:
    game = FakeGame(mode="stepped")
    played = session_for(game, seed=1)
    asyncio.run(played.start())
    played.focus.set_focus("a", played.last_snapshot or {}, {"towns": ["Weston"], "padding": 9})
    reply = asyncio.run(run_round(played, [entry("a", "focus", clear="true")]))["results"]
    assert played.focus.get("a") is None
    assert len(reply["a"]["towns"]) == 2 and "focus" not in reply["a"]


def test_focus_set_in_a_round_cuts_the_actors_of_the_same_round() -> None:
    game = FakeGame(mode="stepped")
    played = session_for(game, seed=1)
    asyncio.run(played.start())
    reply = asyncio.run(
        run_round(
            played,
            [
                entry("a", "focus", towns=["Weston"], padding=5),
                entry("a", "act", moves=[{"command": "ping"}]),
            ],
        )
    )["results"]
    assert len(reply["a"]["snapshot"]["towns"]) == 1
    assert len(reply["a"]["action_results"]) == 1
    assert game.calls("/state/full") == [], "the post-step snapshot serves the focus request too"


def test_a_bad_query_does_not_fail_the_round() -> None:
    game = FakeGame(mode="stepped")
    played = session_for(game, seed=1)
    asyncio.run(played.start())
    reply = asyncio.run(
        run_round(
            played,
            [
                entry("a", "query", query="get_date", parameters="oops"),
                entry("b", "act", moves=[{"command": "ping"}]),
            ],
        )
    )["results"]
    assert reply["a"] == {"error": PARAMETERS_FORMAT_HINT}
    assert reply["b"]["action_results"][0]["status"] == "success"


def test_a_game_refusal_is_reported_to_every_actor_of_the_round() -> None:
    game = FakeGame(mode="stepped")
    played = session_for(game, seed=1)
    asyncio.run(played.start())
    game.closed = True
    reply = asyncio.run(
        run_round(
            played, [
                entry("a", "act", moves=[{"command": "ping"}]),
                entry("b", "act", moves=[{"command": "ping"}]),
                entry("c", "query", query="get_date"),
            ]
        )
    )["results"]
    assert reply["a"]["error"] == "nttd returned 404" and reply["b"] == reply["c"] == reply["a"]
    assert not played.terminated, "a 404 ends only a game that keeps its own clock"


def test_a_query_only_round_reports_the_closed_game_to_agents_and_daemons() -> None:
    game = FakeGame(mode="async_realtime")
    mcp, played = served(game)
    asyncio.run(played.start())
    game.closed = True

    reply = call(mcp, "batch_round", entries=[
        entry("alice", "query", query="get_date"),
        {**entry("daemon:watch", "query", query="get_date"), "owner_tag": "alice"},
    ])["results"]
    ended = {"terminated": True, "end_reason": "session closed", "note": GAME_ENDED_NOTE}
    assert reply == {"alice": ended, "daemon:watch": ended}
    assert played.terminated
    assert call(mcp, "query", query="get_date") == ended
    assert len(game.calls("/state/gs/query")) == 1


def test_after_the_end_actors_and_readers_learn_the_game_ended() -> None:
    game = FakeGame(mode="heartbeat")
    played = session_for(game, seed=1)
    asyncio.run(played.start())
    game.closed = True
    reply = asyncio.run(run_round(played, [entry("a", "act", moves=[{"command": "ping"}]), entry("b", "observe")]))[
        "results"
    ]
    assert reply["a"]["note"] == GAME_ENDED_NOTE
    assert reply["b"]["note"] == GAME_ENDED_NOTE


def test_a_missing_agent_tag_in_an_entry_gets_the_default() -> None:
    game = FakeGame(mode="stepped")
    played = session_for(game, seed=1, default_tag="solo")
    asyncio.run(played.start())
    reply = asyncio.run(run_round(played, [{"tool": "act", "args": {"moves": [{"command": "ping"}]}}]))["results"]
    assert list(reply) == ["solo"]
    ((_, _, body),) = game.calls("/step")
    assert body["actions"][0]["action_id"] == "solo:0"


def test_the_act_schema_refuses_a_name_outside_the_playable_commands() -> None:
    """A query name is not a command. The enum in the schema refuses it before anything
    reaches the game."""
    game = FakeGame(mode="stepped")
    mcp, _ = served(game)
    try:
        call(mcp, "act", moves=[{"command": "get_date"}])
    except Exception as exc:
        assert "get_date" in str(exc)
    else:
        raise AssertionError("a query name was accepted as a command")
    assert game.calls("/step") == []
