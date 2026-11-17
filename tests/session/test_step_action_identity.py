"""A stepped action keeps the id and the agent its caller gave it.

The stepped path used to mint an ``hb_`` id for every action and attach no metadata,
so a caller could pair results to its actions only by position, and the action log
had an empty ``agent_id`` column. A caller may now name each action and its agent.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from nttd.actions.tracker import ActionTracker
from nttd.runtime.orchestrator import Orchestrator
from nttd.state.world import WorldState


def _orchestrator() -> tuple[Orchestrator, MagicMock]:
    client = MagicMock()
    client.connected = True
    client.send_gamescript = AsyncMock(return_value={"success": True, "result": {}})
    recorder = MagicMock()
    orchestrator = Orchestrator(WorldState(), client, recorder=recorder)
    orchestrator.action_tracker = ActionTracker()
    orchestrator.refresh_changed_tiles = AsyncMock()  # type: ignore[method-assign]
    return orchestrator, recorder


def _recorded_envelopes(recorder: MagicMock) -> list[Any]:
    return [call.kwargs["envelope"] for call in recorder.record_action.call_args_list]


def test_a_given_id_and_metadata_come_back_on_the_result_and_in_the_log() -> None:
    orchestrator, recorder = _orchestrator()
    outcomes = asyncio.run(orchestrator._execute_actions([{
        "action": "build_dock", "params": {"x": 1, "y": 2, "company_id": 0},
        "action_id": "crew_3:7", "metadata": {"participant_id": "crew_3"},
    }]))
    assert [outcome.action_id for outcome in outcomes] == ["crew_3:7"]
    envelope = _recorded_envelopes(recorder)[0]
    assert envelope.action_id == "crew_3:7"
    assert envelope.metadata["participant_id"] == "crew_3"
    assert envelope.metadata["participant_type"] == "agent"


def test_an_action_without_an_id_is_minted_one() -> None:
    orchestrator, recorder = _orchestrator()
    outcomes = asyncio.run(orchestrator._execute_actions([
        {"action": "build_dock", "params": {"x": 1, "y": 2, "company_id": 0}},
    ]))
    assert outcomes[0].action_id.startswith("hb_")
    assert _recorded_envelopes(recorder)[0].metadata.get("participant_id") is None


def test_a_refused_action_keeps_its_given_id() -> None:
    """Refusals are results too, and a caller pairs them the same way."""
    orchestrator, recorder = _orchestrator()
    outcomes = asyncio.run(orchestrator._execute_actions([{
        "action": "change_bank_balance", "params": {"company_id": 0},
        "action_id": "crew_1:1", "metadata": {"participant_id": "crew_1"},
    }]))
    assert outcomes[0].action_id == "crew_1:1"
    assert _recorded_envelopes(recorder)[0].metadata["participant_id"] == "crew_1"
