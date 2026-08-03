"""Task instance identity for benchmark runs.

A *task instance* is the reproducible problem a contestant is scored on: a
specific world plus the rules that bound the run. Two runs are only comparable
if they share a task instance, so it needs a stable identifier.

``task_id`` is a hash over the normalised OpenTTD settings and the map seed. It
deliberately excludes anything that does not change the problem -- session ids,
ports, timestamps, screenshot intervals, and which agents played. Editing a
scenario file therefore produces a different ``task_id`` rather than silently
redefining every past and future result recorded under the same name.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

# Settings that describe the run's plumbing rather than the problem itself.
# Excluded from task_id so that, for example, changing the screenshot interval
# does not invent a new task instance.
_NON_TASK_KEYS: frozenset[str] = frozenset({
    "_runtime_mode",
    "_snapshot_interval_days",
    "_screenshot_interval_seconds",
    "_screenshot_type",
    "_save_interval_seconds",
    "_agent_companies",
    "_ai_opponents",
    # Identity, not content: hashed explicitly as part of task_id, so including
    # them in the settings digest too would double-count them.
    "_scenario_id",
    "_scenario_version",
    # Outputs of this computation. They are persisted alongside the settings, so
    # excluding them keeps the hash idempotent -- recomputing from a stored
    # settings dict (as orphan recovery does) must yield the same task_id.
    "_task_id",
    "_settings_digest",
})

_TASK_ID_LENGTH = 16


@dataclass(frozen=True)
class TaskInstance:
    """The identity of a scored problem: which world, under which rules."""

    task_id: str
    scenario_id: str
    scenario_version: str
    seed: int | None
    settings_digest: str

    def as_dict(self) -> dict[str, Any]:
        """Flatten for persistence in a result row or session metadata."""
        return {
            "task_id": self.task_id,
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "seed": self.seed,
            "settings_digest": self.settings_digest,
        }


def normalise_settings(settings: dict[str, str]) -> dict[str, str]:
    """Return only the settings that define the task, in a canonical form.

    Keys are sorted and values stringified so that dict ordering and incidental
    type differences cannot change the digest.
    """
    return {
        key: str(settings[key])
        for key in sorted(settings)
        if key not in _NON_TASK_KEYS
    }


def _digest(payload: Any) -> str:
    """Stable short hex digest over a JSON-serialisable payload."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:_TASK_ID_LENGTH]


def compute_task_instance(
    settings: dict[str, str],
    scenario_id: str,
    scenario_version: str = "1",
) -> TaskInstance:
    """Derive the task instance identity from resolved settings.

    Args:
        settings: The effective OpenTTD settings for the session, including the
            internal ``_map_seed`` key if a seed was configured.
        scenario_id: Stable identifier for the scenario, independent of the file
            path it happens to live at.
        scenario_version: Bumped by the scenario author on any change that
            should invalidate comparison with earlier results.

    Returns:
        A TaskInstance whose ``task_id`` changes if and only if the world or the
        rules changed.
    """
    task_settings = normalise_settings(settings)
    settings_digest = _digest(task_settings)

    raw_seed = settings.get("_map_seed")
    seed = int(raw_seed) if raw_seed not in (None, "") else None

    task_id = _digest({
        "scenario_id": scenario_id,
        "scenario_version": str(scenario_version),
        "seed": seed,
        "settings": task_settings,
    })

    return TaskInstance(
        task_id=task_id,
        scenario_id=scenario_id,
        scenario_version=str(scenario_version),
        seed=seed,
        settings_digest=settings_digest,
    )


def file_digest(path: Any) -> str | None:
    """Hash a file's bytes, or return None if it cannot be read.

    Used to pin artifacts that must not change between a run and its later
    verification -- the resolved scenario file and the GameScript source.
    """
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()[:_TASK_ID_LENGTH]
    except OSError:
        return None
