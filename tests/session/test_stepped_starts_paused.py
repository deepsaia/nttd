"""A stepped session's clock does not move before the contestant's first step.

session_runtime.start_orchestrator has always said, in a comment, that a stepped game "stays
paused in between so deliberation costs nothing". Nothing issued the pause. enter_stepped is
what pauses, and it is reached from exactly one place, the /step/reset endpoint, so the world
ran from the moment OpenTTD spawned until the contestant got around to calling it.

Measured before the fix: a session declaring 182 steps of one game day had reached 2020-05-29
by the time reset landed. 149 of its 182 days were gone, spent on OpenTTD's boot, a 64,516 tile
scan, and the harness's own startup. A contestant with a slower client would start their run
months of game time later on the same declared scenario, and two runs of "182 steps" would not
be the same task.

Checked here without a game, by asserting the orchestrator issues the pause and the manager
calls it for stepped mode and only for stepped mode. The live check is that the game date is
identical before and after a wait, which needs OpenTTD and belongs with the gs_test suite.
"""

from __future__ import annotations

import asyncio
from typing import Any

from nttd.runtime.orchestrator import Orchestrator
from nttd.schemas.game import RuntimeMode
from nttd.state.world import WorldState


class _RecordingClient:
    """An admin client that records rcon rather than talking to a game."""

    def __init__(self) -> None:
        self.connected = True
        self.rcon: list[str] = []

    async def send_rcon(self, command: str) -> dict[str, Any]:
        self.rcon.append(command)
        return {"success": True}


def _orchestrator() -> tuple[Orchestrator, _RecordingClient]:
    client = _RecordingClient()
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.client = client  # type: ignore[assignment]
    orchestrator.world = WorldState()
    orchestrator.recorder = None
    orchestrator._running = False
    orchestrator._step_count = 0
    return orchestrator, client


def test_pausing_at_start_pauses_the_game_and_the_world() -> None:
    orchestrator, client = _orchestrator()
    assert not orchestrator.world.game.paused

    asyncio.run(orchestrator.pause_at_start())

    assert client.rcon == ["pause"], "the game itself was never told to pause"
    assert orchestrator.world.game.paused
    assert orchestrator.world.game.mode is RuntimeMode.STEPPED


def test_the_session_manager_pauses_a_stepped_run_at_start() -> None:
    """The wiring, which is the half that was missing. The orchestrator could pause all
    along; nothing asked it to until the contestant did.

    Read through inspect rather than by slicing the file. Slicing was tried and cut the
    function short at its own nested `async def _on_session_end`, so it reported the pause
    missing while it was there.
    """
    import inspect

    from nttd.runtime.session_manager import SessionManager

    source = inspect.getsource(SessionManager.start_session)

    assert "pause_at_start()" in source, (
        "start_session no longer pauses a stepped run, so its clock runs during boot, the "
        "tile scan, and the contestant's startup"
    )
    # Guarded on the mode, because a real-time run legitimately starts when it starts.
    assert 'runtime_mode == "stepped"' in source


def test_the_start_date_is_recorded_after_the_pause_not_before() -> None:
    """start_game_date is what the result reports the run began at, and it is captured before
    the orchestrator starts. Pausing moves nothing, but the date must be re-read after it so
    the recorded figure is the date the contestant actually receives.
    """
    import inspect

    from nttd.runtime.session_manager import SessionManager

    source = inspect.getsource(SessionManager.start_session)
    body = source.split('runtime_mode == "stepped"')[1]

    assert "pause_at_start()" in body
    assert "start_game_date" in body, (
        "the pause does not re-read start_game_date, so the reported start could predate "
        "the world the contestant is handed"
    )
