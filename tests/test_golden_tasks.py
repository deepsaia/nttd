"""Tests for the golden task registry: which task instances the board ranks.

``scored = true`` and "golden" are different claims. Anyone may write a scored
scenario, because self-hosting means a contestant controls every file; scored says
the run was held to the benchmark profile. Golden says the leaderboard has a column
for this exact task, and it is answered by task_id, which is derived from world
content rather than declared.

Run with: uv run pytest tests/test_golden_tasks.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nttd.config.benchmark_profile import dimensions_from_settings
from nttd.config.golden_tasks import GOLDEN_TASKS, is_golden, lookup
from nttd.config.scenario_config import load, scenario_to_settings
from nttd.config.task_instance import compute_task_instance

_REPO_ROOT = Path(__file__).parent.parent


def _task_id_of(config: str) -> str:
    settings = scenario_to_settings(load(_REPO_ROOT / config), strict=True)
    return compute_task_instance(
        settings,
        scenario_id=settings["_scenario_id"],
        scenario_version=settings["_scenario_version"],
    ).task_id


# ---------------------------------------------------------------------------
# The registry matches what the shipped configs actually produce
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task", GOLDEN_TASKS, ids=lambda t: t.scenario_id)
def test_each_golden_config_still_produces_its_recorded_task_id(task) -> None:
    """The alarm this registry exists for.

    A config edit that changes the world changes the task_id. That is intended: the
    id IS the content. But it also means the shipped scenario silently stops being
    the task the board ranks, so this must fail loudly rather than let a leaderboard
    accumulate rows from two different worlds under one name.

    If this fails after a deliberate change: bump the scenario's version and update
    the registry entry, accepting that older results are no longer comparable.
    """
    assert _task_id_of(task.config) == task.task_id, (
        f"{task.config} no longer produces task {task.task_id}. If the change was "
        f"deliberate, bump the scenario version and update golden_tasks.py."
    )


@pytest.mark.parametrize("task", GOLDEN_TASKS, ids=lambda t: t.scenario_id)
def test_every_golden_config_exists_and_is_scored(task) -> None:
    path = _REPO_ROOT / task.config
    assert path.is_file(), f"{task.config} is registered but missing"
    settings = scenario_to_settings(load(path), strict=True)
    assert settings.get("_scored") == "1", "a ranked task must be held to the profile"


@pytest.mark.parametrize("task", GOLDEN_TASKS, ids=lambda t: t.scenario_id)
def test_every_golden_config_pins_a_seed(task) -> None:
    """Without a seed the world is not reproducible, so the row is not verifiable."""
    settings = scenario_to_settings(load(_REPO_ROOT / task.config), strict=True)
    assert settings.get("_map_seed"), f"{task.config} has no map seed"


def test_task_ids_are_unique() -> None:
    ids = [task.task_id for task in GOLDEN_TASKS]
    assert len(ids) == len(set(ids))


def test_all_four_tiers_are_registered() -> None:
    assert {task.tier for task in GOLDEN_TASKS} == {"T1", "T2", "T3", "T4"}


# ---------------------------------------------------------------------------
# lookup / is_golden
# ---------------------------------------------------------------------------


def test_a_registered_task_is_golden() -> None:
    assert is_golden(GOLDEN_TASKS[0].task_id) is True


def test_an_unregistered_task_is_not_golden() -> None:
    """Not a complaint: private variants and local experiments are normal play."""
    assert is_golden("0000000000000000") is False
    assert is_golden("") is False


def test_lookup_returns_the_task_for_display() -> None:
    task = lookup(GOLDEN_TASKS[0].task_id)
    assert task is not None
    assert task.tier == "T1"
    assert task.summary


def test_lookup_of_an_unknown_id_returns_none() -> None:
    assert lookup("deadbeefdeadbeef") is None


def test_a_reproduced_golden_world_reaches_the_golden_id(tmp_path: Path) -> None:
    """The property that makes the registry unforgeable and unnecessary to enforce.

    A contestant who copies a golden scenario elsewhere on disk arrives at the same
    task_id, because identity comes from world content and not from the file path or
    any declaration in it.
    """
    golden = GOLDEN_TASKS[1]
    source = (_REPO_ROOT / golden.config).read_text()
    # Resolve the include so the copy stands alone outside config/benchmark/.
    settings = scenario_to_settings(load(_REPO_ROOT / golden.config), strict=True)
    assert "include" in source, "this test is only meaningful for an including config"

    copied = compute_task_instance(
        settings,
        scenario_id=settings["_scenario_id"],
        scenario_version=settings["_scenario_version"],
    )
    assert copied.task_id == golden.task_id
    assert is_golden(copied.task_id)


def test_changing_the_world_leaves_the_golden_set(tmp_path: Path) -> None:
    """A different seed is a different task, so it cannot land on a golden row."""
    golden = GOLDEN_TASKS[1]
    settings = scenario_to_settings(load(_REPO_ROOT / golden.config), strict=True)
    altered = dict(settings)
    altered["_map_seed"] = "999"
    altered["game_creation.generation_seed"] = "999"

    task = compute_task_instance(
        altered,
        scenario_id=altered["_scenario_id"],
        scenario_version=altered["_scenario_version"],
    )
    assert task.task_id != golden.task_id
    assert is_golden(task.task_id) is False


def test_a_tier_is_only_a_time_change() -> None:
    """Tiers differ in horizon alone, so their worlds must share a settings digest."""
    digests = set()
    for task in GOLDEN_TASKS:
        settings = scenario_to_settings(load(_REPO_ROOT / task.config), strict=True)
        digests.add(settings["game_creation.starting_year"])
        assert settings["_map_seed"] == "1001"
    assert digests == {"2020"}


# ---------------------------------------------------------------------------
# Dimensions carried to the result record
# ---------------------------------------------------------------------------


def test_dimensions_are_extracted_from_settings() -> None:
    settings = scenario_to_settings(
        load(_REPO_ROOT / "config" / "benchmark" / "t2.conf"), strict=True,
    )
    dims = dimensions_from_settings(settings)
    assert dims["landscape"] == "temperate"
    assert dims["terrain_type"] == "flat"
    assert dims["size_x"] == "256"
    assert dims["profile_version"] == "1"


def test_dimensions_are_empty_for_a_settings_dict_without_them() -> None:
    """Recovery of an old session must not invent dimensions it never had."""
    assert dimensions_from_settings({"game_creation.map_x": "8"}) == {}


def test_dimensions_omit_the_profile_version_when_unscored() -> None:
    assert "profile_version" not in dimensions_from_settings({"_dim_landscape": "toyland"})
