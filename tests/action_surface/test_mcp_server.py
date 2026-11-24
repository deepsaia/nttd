"""The MCP play surface: six tools on one session.

The game commands are not tools. They arrive as enums in the schemas of act and
query, built from the manifest, so a client never learns them from a prompt and a name
outside the manifest cannot be sent.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

import pytest

from nttd.mcp import action_types, server
from nttd.mcp.server import build

TOOLS = {"observe", "act", "query", "list_commands", "focus", "batch_round"}


@pytest.fixture
def mcp() -> Any:
    return build("http://localhost:8000", "ses_test", None, "127.0.0.1", 8100)


@pytest.fixture
def tools(mcp: Any) -> dict[str, Any]:
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


def _call(mcp: Any, tool: str, **kwargs: Any) -> Any:
    result = asyncio.run(mcp.call_tool(tool, kwargs))
    payload = result[1] if isinstance(result, tuple) else result
    if isinstance(payload, dict) and "result" in payload:
        return json.loads(payload["result"])
    return json.loads(payload[0].text)


class TestTheToolSurface:
    def test_there_are_six_tools(self, tools: dict[str, Any]) -> None:
        assert set(tools) == TOOLS

    def test_no_tool_takes_a_session_or_a_company(self, tools: dict[str, Any]) -> None:
        """One server plays one session and one company. Both are launch settings."""
        for name, tool in tools.items():
            properties = tool.inputSchema.get("properties") or {}
            assert "session_id" not in properties, name
            assert "company_id" not in properties, name
            assert "days" not in properties, name

    def test_every_agent_tool_takes_an_optional_agent_tag(self, tools: dict[str, Any]) -> None:
        """So an orchestrator can name the caller, and a single agent can leave it out."""
        for name in TOOLS - {"batch_round"}:
            schema = tools[name].inputSchema
            assert "agent_tag" in schema["properties"], name
            assert "agent_tag" not in schema.get("required", []), name

    def test_every_tool_has_a_description(self, tools: dict[str, Any]) -> None:
        for name, tool in tools.items():
            assert tool.description, name

    def test_the_instructions_are_sent_at_connection(self, mcp: Any) -> None:
        assert mcp.instructions == server.instructions_for("stepped", "global", 0)

    def test_the_instructions_follow_the_session(self) -> None:
        built = build(
            "http://localhost:8000",
            "ses_test",
            None,
            "127.0.0.1",
            8100,
            mode="async_realtime",
            objective="value",
            episode_days=365,
        )
        assert built.instructions == server.instructions_for("async_realtime", "value", 365)

    @pytest.mark.parametrize("mode", ["stepped", "heartbeat", "async_realtime"])
    @pytest.mark.parametrize("objective", ["global", "cargo", "rating", "value"])
    def test_every_mode_and_objective_has_a_text(self, mode: str, objective: str) -> None:
        assert server.instructions_for(mode, objective, 10)

    @pytest.mark.parametrize("mode", ["stepped", "heartbeat", "async_realtime"])
    def test_an_unknown_objective_uses_the_default_and_still_serves_tools(
        self, mode: str, caplog: pytest.LogCaptureFixture,
    ) -> None:
        built = build("http://localhost:8000", "ses_test", None, "127.0.0.1", 8100,
                      mode=mode, objective="ratings", episode_days=365)
        assert built.instructions == server.instructions_for(mode, server.DEFAULT_OBJECTIVE, 365)
        assert "Unknown objective 'ratings'" in caplog.text
        assert set(tool.name for tool in asyncio.run(built.list_tools())) == TOOLS
        assert _call(built, "list_commands", name="ping")["name"] == "ping"


class TestTheVocabularyIsInTheSchema:
    def _enum(self, tool: Any, name: str) -> list[str]:
        return (tool.inputSchema.get("$defs") or {}).get(name, {}).get("enum", [])

    def test_every_playable_action_is_offered(self, tools: dict[str, Any]) -> None:
        from nttd.config import action_manifest

        expected = sorted(n for n, e in action_manifest.ACTIONS.items() if e["tier"] == "participant")
        assert self._enum(tools["act"], "PlayableAction") == expected

    def test_every_observation_is_offered(self, tools: dict[str, Any]) -> None:
        from nttd.config import action_manifest

        expected = sorted(n for n, e in action_manifest.ACTIONS.items() if e["tier"] == "read_only")
        assert self._enum(tools["query"], "ObservationAction") == expected

    def test_operator_actions_are_in_neither(self, tools: dict[str, Any]) -> None:
        from nttd.constants import OPERATOR_ACTIONS

        offered = set(self._enum(tools["act"], "PlayableAction"))
        offered |= set(self._enum(tools["query"], "ObservationAction"))
        assert not offered & OPERATOR_ACTIONS

    def test_the_two_vocabularies_do_not_overlap(self, tools: dict[str, Any]) -> None:
        assert not set(self._enum(tools["act"], "PlayableAction")) & set(
            self._enum(tools["query"], "ObservationAction")
        )

    def test_it_is_built_from_the_manifest_not_a_list(self) -> None:
        source = inspect.getsource(action_types)
        assert "action_manifest.ACTIONS" in source
        assert '"build_road_stop"' not in source


class TestListCommandsNeedsNoGame:
    def test_it_summarises_without_an_argument(self, mcp: Any) -> None:
        from nttd.constants import KNOWN_ACTIONS, READ_ONLY_GS_ACTIONS

        body = _call(mcp, "list_commands")
        assert body["count"] == len(KNOWN_ACTIONS) + len(READ_ONLY_GS_ACTIONS)
        assert "found_town" not in body["commands"]

    def test_it_returns_one_command_in_full(self, mcp: Any) -> None:
        body = _call(mcp, "list_commands", name="set_order_condition")
        assert body["parameters"]["condition"]["enum"]["values"]["OC_UNCONDITIONALLY"] == 5

    def test_a_typo_suggests_the_nearest(self, mcp: Any) -> None:
        body = _call(mcp, "list_commands", name="build_road_stopp")
        assert "build_road_stop" in body["did_you_mean"]

    def test_an_operator_action_is_unknown(self, mcp: Any) -> None:
        body = _call(mcp, "list_commands", name="change_bank_balance")
        assert body["error"].startswith("No such command")


class TestBothKindsOfClient:
    @pytest.mark.parametrize(("choice", "expected"), [("stdio", "stdio"), ("http", "streamable-http")])
    def test_the_transport_maps_to_the_sdk_name(self, choice: str, expected: str) -> None:
        source = inspect.getsource(server.main)
        assert expected in source
        assert f'"{choice}"' in inspect.getsource(server._parse_args) or choice in source

    def test_it_refuses_to_start_without_a_session(self, monkeypatch: Any) -> None:
        import sys

        monkeypatch.setattr(sys, "argv", ["nttd-mcp"])
        monkeypatch.delenv("NTTD_SESSION_ID", raising=False)
        with pytest.raises(SystemExit) as excinfo:
            server.main()
        assert "--session" in str(excinfo.value)

    def test_the_token_is_optional(self) -> None:
        built = build("http://localhost:8000", "ses_test", None, "127.0.0.1", 8100)
        assert built is not None
