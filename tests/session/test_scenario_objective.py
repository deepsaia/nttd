"""The objective is a scenario setting, and the public status carries it and the
episode length, so a client can state both to its agents."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nttd.config import scenario_config
from nttd.config.scenario_config import (
    DEFAULT_OBJECTIVE,
    EndConditionsConfig,
    MaxHeartbeatsConfig,
    ScenarioConfigError,
    TimeLimitConfig,
)
from nttd.runtime.end_conditions import EndConditionChecker
from nttd.runtime.orchestrator import _SECS_PER_GAME_DAY, Orchestrator
from nttd.runtime.session_manager import _apply_objective
from nttd.state.world import WorldState

SCENARIO = """
scenario {{
  name = "objective-test"
  {objective}
  map {{ size_x = 256, size_y = 256, terrain_type = "flat", seed = 1 }}
  companies {{ num_ai_companies = 0, competitors_interval = 0, max_loan = 300000 }}
  runtime {{ mode = "async_realtime" }}
  heartbeat {{ interval_days = 1 }}
  end_conditions {{
    logic = "any"
    time_limit {{ enabled = true, wall_minutes = 12 }}
    max_heartbeats {{ enabled = false, count = 366 }}
  }}
}}
"""


def scenario_file(tmp_path: Path, objective_line: str) -> Path:
    path = tmp_path / "scenario.conf"
    path.write_text(SCENARIO.format(objective=objective_line))
    return path


def test_the_objective_is_read_from_the_scenario(tmp_path: Path) -> None:
    assert scenario_config.load(scenario_file(tmp_path, 'objective = "cargo"')).objective == "cargo"


def test_a_scenario_without_an_objective_gets_the_default(tmp_path: Path) -> None:
    assert scenario_config.load(scenario_file(tmp_path, "")).objective == DEFAULT_OBJECTIVE


def test_an_unknown_objective_is_refused_in_strict_mode(tmp_path: Path) -> None:
    cfg = scenario_config.load(scenario_file(tmp_path, 'objective = "ratings"'))
    with pytest.raises(ScenarioConfigError) as caught:
        scenario_config.scenario_to_settings(cfg, strict=True)
    assert "objective" in str(caught.value)


def test_only_a_non_default_objective_is_stored_so_existing_task_ids_hold(tmp_path: Path) -> None:
    default = scenario_config.scenario_to_settings(scenario_config.load(scenario_file(tmp_path, "")), strict=True)
    explicit = scenario_config.scenario_to_settings(
        scenario_config.load(scenario_file(tmp_path, 'objective = "global"')), strict=True,
    )
    other = scenario_config.scenario_to_settings(
        scenario_config.load(scenario_file(tmp_path, 'objective = "value"')), strict=True,
    )
    assert "_objective" not in default and "_objective" not in explicit
    assert other["_objective"] == "value"


def test_loading_a_scenario_publishes_its_objective_and_length(tmp_path: Path) -> None:
    orchestrator = Orchestrator(WorldState(), MagicMock())
    orchestrator.load_scenario(scenario_config.load(scenario_file(tmp_path, 'objective = "rating"')))
    assert orchestrator.world.game.objective == "rating"
    assert orchestrator.world.game.episode_days == round(12 * 60 / _SECS_PER_GAME_DAY)


def test_a_started_or_recovered_session_takes_its_stored_objective() -> None:
    runtime = MagicMock()
    runtime.orchestrator = Orchestrator(WorldState(), MagicMock())
    _apply_objective(runtime, {"_objective": "cargo"})
    assert runtime.orchestrator.world.game.objective == "cargo"
    _apply_objective(runtime, {})
    assert runtime.orchestrator.world.game.objective == DEFAULT_OBJECTIVE


def checker(logic: str = "any", steps: int | None = None, minutes: float | None = None) -> EndConditionChecker:
    return EndConditionChecker(EndConditionsConfig(
        logic=logic,
        time_limit=TimeLimitConfig(enabled=minutes is not None, wall_minutes=minutes or 0),
        max_heartbeats=MaxHeartbeatsConfig(enabled=steps is not None, count=steps or 0),
    ))


def test_a_step_bound_lasts_steps_times_days_per_step() -> None:
    assert checker(steps=100).episode_days(3, 2.0) == 300


def test_a_time_bound_lasts_the_wall_limit_at_the_economy_clock() -> None:
    assert checker(minutes=12).episode_days(1, 2.0) == 360


def test_with_both_bounds_any_ends_at_the_first_and_all_at_the_last() -> None:
    assert checker("any", steps=100, minutes=12).episode_days(1, 2.0) == 100
    assert checker("all", steps=100, minutes=12).episode_days(1, 2.0) == 360


def test_a_run_with_neither_bound_has_no_length() -> None:
    assert checker().episode_days(1, 2.0) == 0


def test_changing_the_step_size_republishes_the_length() -> None:
    orchestrator = Orchestrator(WorldState(), MagicMock())
    orchestrator.configure_end_conditions(EndConditionsConfig(
        time_limit=TimeLimitConfig(enabled=False), max_heartbeats=MaxHeartbeatsConfig(enabled=True, count=10),
    ))
    orchestrator.set_heartbeat_interval(7)
    assert orchestrator.world.game.episode_days == 70
