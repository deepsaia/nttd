"""Tests for task instance identity.

task_id answers "which problem was this run scored on". It must be stable under
things that do not change the problem (dict ordering, recomputation, screenshot
settings) and must move when the world or the rules change. A leaderboard that
gets this wrong silently compares runs from different worlds.

Run with: uv run pytest tests/test_task_instance.py -v
"""

from __future__ import annotations

from pathlib import Path

from nttd.config.task_instance import (
    compute_task_instance,
    file_digest,
    normalise_settings,
)

_BASE_SETTINGS = {
    "game_creation.map_x": "8",
    "game_creation.map_y": "8",
    "difficulty.terrain_type": "2",
    "game_creation.generation_seed": "1001",
    "_map_seed": "1001",
    "_scenario_id": "bench-30min",
}


def _task(**overrides: str):
    settings = {**_BASE_SETTINGS, **overrides}
    return compute_task_instance(settings, scenario_id=settings["_scenario_id"])


# ---------------------------------------------------------------------------
# Stability: things that must NOT change task_id
# ---------------------------------------------------------------------------


def test_same_inputs_give_same_id() -> None:
    assert _task().task_id == _task().task_id


def test_dict_ordering_does_not_matter() -> None:
    """Settings arrive from configs and HTTP bodies, so order is incidental."""
    reversed_settings = dict(reversed(list(_BASE_SETTINGS.items())))
    a = compute_task_instance(_BASE_SETTINGS, "bench-30min")
    b = compute_task_instance(reversed_settings, "bench-30min")
    assert a.task_id == b.task_id


def test_recomputation_is_idempotent() -> None:
    """Orphan recovery recomputes from settings that already carry the outputs.

    _task_id and _settings_digest are persisted next to the settings, so if they
    fed back into the hash a recovered session would report a different task_id
    than the run it is recovering.
    """
    first = _task()
    with_outputs = {
        **_BASE_SETTINGS,
        "_task_id": first.task_id,
        "_settings_digest": first.settings_digest,
    }
    second = compute_task_instance(with_outputs, "bench-30min")
    assert second.task_id == first.task_id


def test_plumbing_settings_do_not_change_id() -> None:
    """Screenshot cadence and agent counts describe the run, not the problem."""
    baseline = _task()
    noisy = compute_task_instance(
        {
            **_BASE_SETTINGS,
            "_screenshot_interval_seconds": "30",
            "_screenshot_type": "giant",
            "_save_interval_seconds": "60",
            "_snapshot_interval_days": "7",
            "_runtime_mode": "heartbeat",
            "_agent_companies": "3",
            "_ai_opponents": "2",
        },
        "bench-30min",
    )
    assert noisy.task_id == baseline.task_id


# ---------------------------------------------------------------------------
# Sensitivity: things that MUST change task_id
# ---------------------------------------------------------------------------


def test_seed_change_changes_id() -> None:
    assert _task(_map_seed="2002").task_id != _task().task_id


def test_a_settings_change_changes_id() -> None:
    """What a scenario version used to be for, done by the settings themselves.

    A version number had to be remembered, and it duplicated this: any edit worth
    invalidating a comparison changes the settings, which changes the digest.
    """
    assert _task(**{"difficulty.terrain_type": "3"}).task_id != _task().task_id


def test_scenario_id_change_changes_id() -> None:
    assert _task(_scenario_id="other-bench").task_id != _task().task_id


def test_world_setting_change_changes_id() -> None:
    """Terrain is part of the problem, so changing it is a different task."""
    changed = _task(**{"difficulty.terrain_type": "3"})
    assert changed.task_id != _task().task_id
    assert changed.settings_digest != _task().settings_digest


# ---------------------------------------------------------------------------
# Fields and helpers
# ---------------------------------------------------------------------------


def test_seed_is_parsed_as_int() -> None:
    assert _task().seed == 1001


def test_missing_seed_is_none() -> None:
    """An unseeded run is recorded as such rather than defaulting to a number."""
    settings = {k: v for k, v in _BASE_SETTINGS.items() if k != "_map_seed"}
    task = compute_task_instance(settings, "bench-30min")
    assert task.seed is None


def test_as_dict_round_trips_fields() -> None:
    task = _task()
    payload = task.as_dict()
    assert payload == {
        "task_id": task.task_id,
        "scenario_id": "bench-30min",
        "seed": 1001,
        "settings_digest": task.settings_digest,
    }


def test_normalise_drops_plumbing_and_sorts() -> None:
    result = normalise_settings(
        {"b": "2", "a": "1", "_screenshot_type": "minimap", "_task_id": "x"}
    )
    assert result == {"a": "1", "b": "2"}
    assert list(result) == ["a", "b"]


def test_file_digest_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    path = tmp_path / "scenario.conf"
    path.write_text("scenario { name = 'a' }")
    first = file_digest(path)
    assert first is not None
    assert file_digest(path) == first

    path.write_text("scenario { name = 'b' }")
    assert file_digest(path) != first


def test_file_digest_returns_none_when_unreadable(tmp_path: Path) -> None:
    """A missing GameScript or scenario must not crash the result record."""
    assert file_digest(tmp_path / "does_not_exist.conf") is None
