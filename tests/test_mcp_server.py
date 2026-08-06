"""The MCP play surface.

What this replaced had 33 tools, 30 of them getters wrapping one REST call each, and no
way to act or step: an agent connected to it could look at the game and do nothing. The
shape grew with the API rather than with the game.

Five tools now, which raises the fair objection that 120 actions have been hidden inside
one of them. They have not: action_type is an enum, so every name arrives in the tool
schema where a client already looks, rather than in a prompt where it would be guessed
at.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from nttd.mcp.server import build


@pytest.fixture
def mcp() -> Any:
    return build("http://localhost:8000", "ses_test", "tok_test", "127.0.0.1", 8100)


@pytest.fixture
def tools(mcp: Any) -> dict[str, Any]:
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


class TestTheToolSurface:
    def test_there_are_five_tools(self, tools: dict[str, Any]) -> None:
        assert set(tools) == {
            "nttd_observe", "nttd_act", "nttd_step", "nttd_query", "nttd_actions",
        }

    def test_no_tool_takes_a_session(self, tools: dict[str, Any]) -> None:
        """One server is one seat. A session argument would let a client address a game
        it was not given, and would put the burden of tracking it on the model."""
        for name, tool in tools.items():
            properties = tool.inputSchema.get("properties") or {}
            assert "session_id" not in properties, name
            assert "company_id" not in properties, name

    def test_every_tool_explains_when_to_use_it(self, tools: dict[str, Any]) -> None:
        """A five-tool surface only works if each says what it is for. nttd_act and
        nttd_step overlap unless the descriptions distinguish them."""
        for name, tool in tools.items():
            assert tool.description and len(tool.description) > 80, name
        assert "stepped" in tools["nttd_act"].description
        assert "real-time" in tools["nttd_act"].description


class TestTheVocabularyIsInTheSchema:
    """The whole argument for collapsing 120 actions into two tools."""

    def _enum(self, tool: Any, name: str) -> list[str]:
        return (tool.inputSchema.get("$defs") or {}).get(name, {}).get("enum", [])

    def test_every_playable_action_is_offered(self, tools: dict[str, Any]) -> None:
        from nttd.config import action_manifest

        expected = sorted(
            n for n, e in action_manifest.ACTIONS.items() if e["tier"] == "participant"
        )
        assert self._enum(tools["nttd_act"], "PlayableAction") == expected

    def test_every_observation_is_offered(self, tools: dict[str, Any]) -> None:
        from nttd.config import action_manifest

        expected = sorted(
            n for n, e in action_manifest.ACTIONS.items() if e["tier"] == "read_only"
        )
        assert self._enum(tools["nttd_query"], "ObservationAction") == expected

    def test_operator_actions_are_in_neither(self, tools: dict[str, Any]) -> None:
        """No session can run one, so offering it would be advertising a refusal."""
        from nttd.constants import OPERATOR_ACTIONS

        offered = set(self._enum(tools["nttd_act"], "PlayableAction"))
        offered |= set(self._enum(tools["nttd_query"], "ObservationAction"))
        assert not offered & OPERATOR_ACTIONS

    def test_the_two_vocabularies_do_not_overlap(self, tools: dict[str, Any]) -> None:
        """An observation is not a move, and a move is not something to read."""
        assert not set(self._enum(tools["nttd_act"], "PlayableAction")) & set(
            self._enum(tools["nttd_query"], "ObservationAction")
        )

    def test_it_is_built_from_the_manifest_not_a_list(self) -> None:
        """A hand-kept list here would be the defect the manifest replaced, one layer
        up. Adding an action to the GameScript and regenerating should be the whole of
        exposing it."""
        import inspect

        from nttd.mcp import action_types

        source = inspect.getsource(action_types)
        assert "action_manifest.ACTIONS" in source
        assert '"build_road_stop"' not in source


class FakeRoutes:
    """Records what the client sent, and answers plausibly."""

    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if request.url.path.endswith("/state/full"):
            return httpx.Response(200, json={"companies": [], "towns": []})
        if request.url.path.endswith("/step"):
            return httpx.Response(200, json={"observation": {}, "game_date": 10})
        if request.url.path.endswith("/interpret/validate"):
            return httpx.Response(200, json={"valid": True, "errors": {}})
        return httpx.Response(200, json={"success": True})


def _wire(client: Any, routes: FakeRoutes) -> None:
    """Point a client at the fake without changing how it builds requests."""
    client._http = httpx.AsyncClient(
        base_url="http://nttd.test",
        transport=httpx.MockTransport(routes.handle),
        headers=client._http.headers,
    )


class TestTheClientPlaysAsOneCompany:
    """The client this replaced predated participant tokens: it called the legacy
    unprefixed paths, registered through /agents/connect, and put company_id in every
    envelope, which the participant routes now overwrite from the token."""

    def _client(self) -> Any:
        from nttd.mcp.participant_client import ParticipantClient

        return ParticipantClient("http://nttd.test", "ses_test", "tok_test")

    def test_it_sends_the_participant_token(self) -> None:
        from nttd.api.participant_auth import TOKEN_HEADER

        client, routes = self._client(), FakeRoutes()
        _wire(client, routes)
        asyncio.run(client.observe())
        assert routes.seen[0].headers[TOKEN_HEADER] == "tok_test"

    def test_it_calls_the_participant_tier(self) -> None:
        client, routes = self._client(), FakeRoutes()
        _wire(client, routes)
        asyncio.run(client.observe())
        assert routes.seen[0].url.path.startswith("/v1/participant/sessions/ses_test")

    def test_it_does_not_send_a_company_id(self) -> None:
        """The route takes the company from the token and overwrites the body. Sending
        one read as though the caller chose."""
        client, routes = self._client(), FakeRoutes()
        _wire(client, routes)
        asyncio.run(client.submit("build_dock", {"x": 5, "y": 6}))
        body = json.loads(routes.seen[0].content)
        assert "company_id" not in body
        assert body["action_type"] == "build_dock"

    def test_a_step_carries_its_actions(self) -> None:
        """Actions and the advance are one request. Submitting separately and then
        stepping would reintroduce the guess about when they landed."""
        client, routes = self._client(), FakeRoutes()
        _wire(client, routes)
        asyncio.run(client.step([{"action": "build_dock", "params": {"x": 1, "y": 2}}]))
        body = json.loads(routes.seen[0].content)
        assert body["actions"][0]["action"] == "build_dock"
        assert "days" not in body, "an unset step size must not override the scenario"

    def test_status_is_read_from_the_public_tier(self) -> None:
        """It belongs to nobody in particular, and asking the participant tier for it
        would 404."""
        client, routes = self._client(), FakeRoutes()
        _wire(client, routes)
        asyncio.run(client.status())
        assert routes.seen[0].url.path == "/v1/public/sessions/ses_test/status"


class TestTheManifestTool:
    def _call(self, **kwargs: Any) -> dict[str, Any]:
        from mcp.server.fastmcp import FastMCP

        from nttd.mcp.tools import catalogue

        server = FastMCP("t")
        catalogue.register(server)
        result = asyncio.run(server.call_tool("nttd_actions", kwargs))
        payload = result[1] if isinstance(result, tuple) else result
        if isinstance(payload, dict) and "result" in payload:
            return json.loads(payload["result"])
        return json.loads(payload[0].text)

    def test_it_summarises_without_an_argument(self) -> None:
        """The full manifest is large. Choosing an action needs one line each."""
        body = self._call()
        assert body["count"] == 120
        assert "found_town" not in body["actions"]

    def test_it_returns_one_action_in_full(self) -> None:
        body = self._call(action_type="set_order_condition")
        assert body["parameters"]["condition"]["enum"]["values"]["OC_UNCONDITIONALLY"] == 5

    def test_a_typo_suggests_the_nearest(self) -> None:
        body = self._call(action_type="build_road_stopp")
        assert "build_road_stop" in body["did_you_mean"]


class TestBothKindsOfClient:
    """stdio for an agent that launches the server, streamable HTTP for a framework that
    connects to one already running. Both are real consumers here."""

    @pytest.mark.parametrize(
        ("choice", "expected"), [("stdio", "stdio"), ("http", "streamable-http")],
    )
    def test_the_transport_maps_to_the_sdk_name(self, choice: str, expected: str) -> None:
        import inspect

        from nttd.mcp import server

        source = inspect.getsource(server.main)
        assert expected in source
        assert f'"{choice}"' in inspect.getsource(server._parse_args) or choice in source

    def test_it_refuses_to_start_without_a_seat(self, monkeypatch: Any) -> None:
        """Under stdio a missing token surfaces as every tool failing with a 401, which
        reads as nttd being broken rather than as the server being misconfigured."""
        import sys

        from nttd.mcp import server

        monkeypatch.setattr(sys, "argv", ["nttd-mcp"])
        for name in ("NTTD_SESSION_ID", "NTTD_PARTICIPANT_TOKEN"):
            monkeypatch.delenv(name, raising=False)

        with pytest.raises(SystemExit) as excinfo:
            server.main()
        assert "session attach" in str(excinfo.value)
