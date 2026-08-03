"""The golden task registry: which task instances the leaderboard ranks.

Anyone may write a scenario, including a scored one. Self-hosting means a
contestant controls every file, so ``scored = true`` cannot mean "official" -- it
means "held to the benchmark profile", which is a statement about the rules the run
obeyed, not about whether the board should show it.

Golden is the separate question, and it is answered by ``task_id`` rather than by a
flag. A task_id is derived from the world content: the scenario id and version, the
seed, and the normalised OpenTTD settings. So a contestant who reproduces a golden
world exactly arrives at the golden task_id automatically, and one who changes
anything at all -- a different seed, a larger map, denser industry -- arrives at a
different id and simply is not that task. Nothing to enforce and nothing to forge:
the identity IS the content.

That leaves the registry doing one honest job: naming the task instances the board
has a column for, so a result can be told apart from a run of a private variant.
Both are legitimate play. Only one is comparable to other rows.

The ids here are recorded, not computed at import, because the point of a registry
is to notice when a shipped scenario stops producing the task it used to. A config
edit that changes the world changes the id, and the test comparing the two fails --
which is the intended alarm, not a nuisance. Bump the scenario's ``version`` and
update the entry deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldenTask:
    """A task instance the leaderboard ranks.

    Attributes:
        task_id: The derived identity. A run whose task_id matches this is a run of
            this task, whoever hosted it and whatever played it.
        scenario_id: The scenario's declared id, carried for display.
        config: Repo-relative path to the scenario, so a contestant can play it.
        tier: Which time horizon, and therefore which section of the board.
        summary: What varies from the standard world, in words a board reader can
            use to judge comparability.
    """

    task_id: str
    scenario_id: str
    config: str
    tier: str
    summary: str


# One entry per ranked task instance. Any contestant shape may play any of them: an
# LLM agent, a multi-agent system, an RL policy, an ES candidate, or a human. The
# task says nothing about who plays it, which is the reason the runner config lives
# outside the scenario.
GOLDEN_TASKS: tuple[GoldenTask, ...] = (
    GoldenTask(
        task_id="cf7ee1c24f6cfbf8",
        scenario_id="benchmark-t1",
        config="config/benchmark/t1.conf",
        tier="T1",
        summary="15 min, 256x256 temperate flat",
    ),
    GoldenTask(
        task_id="78d654bd98f21b4b",
        scenario_id="benchmark-t2",
        config="config/benchmark/t2.conf",
        tier="T2",
        summary="30 min, 256x256 temperate flat",
    ),
    GoldenTask(
        task_id="972b6086a2a2ef03",
        scenario_id="benchmark-t3",
        config="config/benchmark/t3.conf",
        tier="T3",
        summary="60 min, 256x256 temperate flat",
    ),
    GoldenTask(
        task_id="e4ebb1df078a974f",
        scenario_id="benchmark-t4",
        config="config/benchmark/t4.conf",
        tier="T4",
        summary="120 min, 256x256 temperate flat",
    ),
)

_BY_TASK_ID: dict[str, GoldenTask] = {task.task_id: task for task in GOLDEN_TASKS}


def lookup(task_id: str) -> GoldenTask | None:
    """Return the golden task with this id, or None if it is not a ranked task."""
    return _BY_TASK_ID.get(task_id)


def is_golden(task_id: str) -> bool:
    """Whether a result belongs on the leaderboard.

    A False here is not a complaint. It means the run was of a scenario the board
    has no column for, which is the normal case for local experimentation and for
    the private variants a contestant builds while preparing.
    """
    return task_id in _BY_TASK_ID
