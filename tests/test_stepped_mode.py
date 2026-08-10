"""Stepped mode: client-driven stepping for RL, ES and multi-agent entries.

A step is one synchronous call that flushes a batch of actions, advances the world a
fixed number of game-days, re-pauses, and returns the observation. Between steps the
game is paused, so deliberation costs no game time -- which is the entire reason to
step rather than play in real time.

This is NOT the heartbeat loop. That one runs on the server and waits
``action_window_seconds`` of wall clock for actions to arrive, which truncates a slow
policy and idles for a fast one. A stepped run exists precisely because deliberation
should be unbounded, so a wall-clock deadline contradicts it.

Verified against a live OpenTTD 15.3 session: 20 seconds of thinking advanced the
game by 0 days, and a step with one action applied it, advanced exactly 15 days, and
returned only after the world had moved.

Run with: uv run pytest tests/test_stepped_mode.py -v

The gate that admits a step is tested separately, in test_step_gate.py.
"""

from __future__ import annotations

import inspect

from nttd.api import control_routes
from nttd.runtime.orchestrator import Orchestrator
from nttd.schemas.game import RuntimeMode
from nttd.schemas.step_result import StepRequest, StepResult


def _code_only(source: str) -> str:
    """Strip comment lines.

    These tests assert on the ORDER of calls, and a comment naming a later call
    would otherwise satisfy an index() lookup before the call itself does.
    """
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )


# ---------------------------------------------------------------------------
# The barrier's order of operations
# ---------------------------------------------------------------------------
# Order is the whole correctness argument: actions must land against a still world,
# and the observation must be taken after the advance rather than before it.


def test_actions_execute_with_the_game_running() -> None:
    """A GameScript DoCommand completes on a game tick, so while the game is paused
    it never completes and every build times out after 10s.

    Verified against OpenTTD 15.3: the same build_road_stop timed out while paused
    and succeeded in 0.04s unpaused. command_pause_level does not change this -- it
    governs what a human client may issue, not whether the script's command queue
    drains. So the flush has to sit between the unpause and the advance.
    """
    source = _code_only(inspect.getsource(Orchestrator.step))
    assert source.index("_unpause") < source.index("_execute_actions")
    assert source.index("_execute_actions") < source.index("_wait_until_game_date")


def test_the_step_advances_before_it_observes() -> None:
    """Observing first would hand back the pre-step world and make the reward for a
    step describe the step before it."""
    source = _code_only(inspect.getsource(Orchestrator.step))
    assert source.index("_wait_until_game_date") < source.index("_refresh_world_from_gs")


def test_the_target_date_is_fixed_before_the_world_moves() -> None:
    """Duration-based waiting would make a step with a slow batch cover more game
    time than one with an empty batch, so two runs of the same scenario would span
    different horizons."""
    source = _code_only(inspect.getsource(Orchestrator.step))
    assert source.index("target_date") < source.index("_unpause")


def test_an_overrunning_batch_does_not_extend_the_step() -> None:
    """Pathfinding can take a minute, which is ~30 game-days. Waiting for a target
    already passed must return rather than advance another full interval."""
    source = _code_only(inspect.getsource(Orchestrator._wait_until_game_date))
    assert "remaining <= 0" in source
    assert "return" in source


def test_days_advanced_reports_what_happened() -> None:
    """Not the requested interval: a slow batch can outrun it, and a reader
    reconstructing the run needs the real figure."""
    source = _code_only(inspect.getsource(Orchestrator.step))
    assert "game_date - start_date" in source


def test_the_step_repauses_before_observing() -> None:
    """A snapshot read while the world runs is torn: the date can move between the
    company read and the vehicle read."""
    source = _code_only(inspect.getsource(Orchestrator.step))
    assert source.index("_pause") < source.index("_refresh_world_from_gs")


def test_the_step_checks_end_conditions_after_advancing() -> None:
    """The condition that ends a run is met by the advance, so checking before it
    would always report the previous step's verdict."""
    source = _code_only(inspect.getsource(Orchestrator.step))
    assert source.index("_refresh_world_from_gs") < source.index("_end_checker")


# ---------------------------------------------------------------------------
# Stepped mode runs no server loop
# ---------------------------------------------------------------------------


def test_stepped_is_a_distinct_runtime_mode() -> None:
    assert RuntimeMode.STEPPED.value == "stepped"


def test_stepped_mode_starts_no_orchestrator_task() -> None:
    """A loop would move the world underneath a policy that is still thinking,
    which is the thing stepping exists to avoid."""
    source = inspect.getsource(
        __import__("nttd.runtime.session_runtime", fromlist=["x"]).SessionRuntime
        .start_orchestrator,
    )
    stepped = source.index('mode == "stepped"')
    heartbeat = source.index('mode == "heartbeat"')
    assert stepped < heartbeat, "the stepped branch must return before a task is made"
    assert "return" in source[stepped:heartbeat]


def test_entering_stepped_pauses_the_game() -> None:
    """The opening observation must be of a still world, and the world must stay
    still until the contestant asks for a step."""
    source = _code_only(inspect.getsource(Orchestrator.enter_stepped))
    assert "_pause" in source
    assert source.index("_pause") < source.index("snapshot")


# ---------------------------------------------------------------------------
# The same guards as every other action path
# ---------------------------------------------------------------------------


def test_stepped_actions_pass_the_shared_admission_check() -> None:
    """A step flushes through _execute_actions, which calls the gate. Without this a
    policy could reach operator-tier commands the REST path refuses -- which is
    exactly the bypass that existed before the gate."""
    source = _code_only(inspect.getsource(Orchestrator._execute_actions))
    assert "admit(" in source


def test_the_step_route_scopes_every_action_to_the_token() -> None:
    """Per action, not once per request: a batch must not be able to smuggle a
    rival's company_id past the scope check in its second entry."""
    source = _code_only(inspect.getsource(control_routes.take_step))
    scope = source.index("apply_company_scope")
    loop = source.index("for entry in request.actions")
    assert loop < scope, "scoping must happen inside the loop over actions"


def test_a_scored_run_cannot_choose_its_step_size() -> None:
    """Step size decides how much world each decision buys, so it belongs to the
    task. A contestant passing days=1 would take many more decisions per horizon."""
    source = _code_only(inspect.getsource(control_routes.take_step))
    assert "scored_lock.scored" in source
    assert "403" in source


# ---------------------------------------------------------------------------
# The step contract
# ---------------------------------------------------------------------------


def test_a_step_carries_a_variable_length_batch() -> None:
    """Not one action per step. The queue-and-flush design accumulates while paused
    and flushes on stepping, so a policy may lay a whole route in one step."""
    request = StepRequest(actions=[{"action": "build_road_stop", "params": {}}] * 7)
    assert len(request.actions) == 7


def test_a_step_with_no_actions_is_legitimate() -> None:
    """Waiting while vehicles earn is a real move, and a policy must be able to
    make it."""
    assert StepRequest().actions == []


def test_the_step_result_reports_what_a_step_was_worth() -> None:
    """A reader reconstructing a run needs the interval, since a scenario may
    change it."""
    fields = set(StepResult.model_fields)
    assert {"snapshot", "step", "days_advanced", "terminated", "end_reason"} <= fields


def test_the_step_result_carries_no_reward() -> None:
    """Reward is the contestant's choice of what to optimise. A reward defined by
    nttd would have every RL entry optimising the platform's opinion, and the score
    a leaderboard ranks on is deliberately separate from it.
    """
    assert "reward" not in StepResult.model_fields


def test_the_default_step_size_comes_from_the_scenario() -> None:
    """So a scenario sets the step size once rather than every caller repeating it."""
    source = _code_only(inspect.getsource(Orchestrator.step))
    assert "_heartbeat_interval_days" in source


# ---------------------------------------------------------------------------
# No action ceiling, in either mode
# ---------------------------------------------------------------------------
# There was one, at 15 per submission. It is gone: how many actions to spend is the
# contestant's own optimisation problem, in stepped play as much as in real time. A
# stepped run is bounded by how many steps it takes and how many game-days each step
# advances, both fixed by the scenario, so an unbounded batch cannot buy more world.


def test_nothing_checks_a_batch_size_any_more() -> None:
    assert not hasattr(Orchestrator, "check_batch_size")


def test_the_step_does_not_measure_its_batch() -> None:
    """A step flushes whatever it is given. What bounds a stepped run is how many
    steps it takes and how many game-days each advances, both fixed by the scenario,
    so a larger batch cannot buy more world than another contestant gets."""
    source = _code_only(inspect.getsource(Orchestrator.step))
    for word in ("ceiling", "budget", "check_batch_size", "too large"):
        assert word not in source.lower(), f"step still limits its batch: {word}"



def test_recording_a_successful_action_does_not_raise() -> None:
    """The regression: error=None failed pydantic validation for ActionResult.error,
    and the try/except turned that into a silent gap in the audit log."""
    from nttd.schemas.action_envelope import ActionEnvelope, ActionMode
    from nttd.schemas.action_result import ActionResult, ActionStatus

    # Construct exactly what _record_action builds for a success.
    result = ActionResult(
        action_id="hb_test",
        status=ActionStatus.SUCCESS,
        error="",
        changed_entities={"station_id": 2},
    )
    assert result.error == ""

    envelope = ActionEnvelope(
        action_id="hb_test", action_type="build_road_stop", parameters={},
        company_id=0, mode=ActionMode.ATOMIC,
    )
    assert envelope.action_id == "hb_test"


def test_record_action_passes_a_string_error() -> None:
    """`error or None` would send None for a success, which ActionResult refuses."""
    source = _code_only(inspect.getsource(Orchestrator._record_action))
    assert "error=error," in source, "error must be passed through as a string"
    assert "error or None" not in source


def test_every_outcome_is_recorded() -> None:
    """Success, failure, refusal, and disconnection all leave a row, so the log has
    no silent gaps for a verifier to trip over."""
    source = _code_only(inspect.getsource(Orchestrator._execute_actions))
    assert source.count("_record_action") >= 4


# ---------------------------------------------------------------------------
# The step size, and where the date comes from
# ---------------------------------------------------------------------------


def test_the_step_size_reaches_the_runtime() -> None:
    """A scenario's heartbeat.interval_days was never emitted into settings, so the
    orchestrator kept its 30-day default: a scenario asking for 15 silently got 30,
    every step covered twice the intended world, and the run reached its horizon in
    half the steps."""
    from nttd.config.scenario_config import load, scenario_to_settings

    settings = scenario_to_settings(
        load(
            __import__("pathlib").Path(__file__).parent.parent
            / "config/benchmark/t2_stepped_example.conf",
        ),
        strict=True,
    )
    assert settings["_heartbeat_interval_days"] == "15"


def test_the_step_size_is_applied_on_start_and_on_recovery() -> None:
    """A restart that reverted the step size would change the task mid-run."""
    from nttd.runtime import session_manager

    source = _code_only(inspect.getsource(session_manager))
    assert source.count("_apply_step_size(") >= 3, (
        "expected the helper plus a call on both the start and recovery paths"
    )


def test_the_start_date_is_read_from_the_gamescript() -> None:
    """world.game.game_date is fed by admin DATE packets, which arrive daily and
    only while the game is running -- so a value read while paused is as old as the
    pause. Measuring a step from it reported 150 days for a 15-day step,
    intermittently, which is worse than always because the number looks plausible.
    """
    source = _code_only(inspect.getsource(Orchestrator.step))
    assert "_authoritative_game_date" in source
    assert "self.world.game.game_date" not in source.split("start_date")[1][:200]


def test_reading_the_date_falls_back_to_the_cache() -> None:
    """A step that cannot read the date should still advance."""
    source = _code_only(inspect.getsource(Orchestrator._authoritative_game_date))
    assert "except Exception" in source
    assert "return self.world.game.game_date" in source
