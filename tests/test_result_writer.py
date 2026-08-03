"""Tests for result.parquet, the immutable record a leaderboard ingests.

The record must be complete enough to answer "what exactly produced this number",
and honest about what it does not know -- an absent seed or digest is recorded as
absent rather than guessed.

Run with: uv run pytest tests/test_result_writer.py -v
"""

from __future__ import annotations

from pathlib import Path

from nttd.analysis.score import rank_companies
from nttd.config.task_instance import compute_task_instance
from nttd.db.result_writer import ResultWriter, read_result
from nttd.schemas.company import Company

_SETTINGS = {
    "game_creation.map_x": "8",
    "difficulty.terrain_type": "2",
    "_map_seed": "1001",
    "_scenario_id": "bench-30min",
    "_scenario_version": "1",
}


def _write(tmp_path: Path, **overrides: object) -> list[dict]:
    """Write a result for a two-company session and read it back."""
    companies = [
        Company(id=0, name="AgentCorp", performance_rating=740, q0_cargo=1200,
                value=250_000, money=90_000, loan=100_000),
        Company(id=1, name="Rival", performance_rating=380, q0_cargo=300,
                value=110_000, money=20_000, loan=200_000),
    ]
    task = compute_task_instance(_SETTINGS, "bench-30min", "1")
    kwargs: dict = {
        "session_id": "ses_test",
        "scores": rank_companies(companies),
        "task": task,
        "runtime_mode": "async_realtime",
        "end_reason": "time_limit",
        "wall_seconds": 1800.5,
        "start_game_date": 715_000,
        "end_game_date": 715_912,
        "participants": {
            0: {
                "agent_id": "road_agent", "nttd_framework": "langchain",
                "model": "gpt-5.2", "total_actions": 42, "successful_actions": 40,
                "prompt_tokens": 120_000, "completion_tokens": 8_000,
                "total_cost": 3.91, "cost_is_estimated": False,
            },
        },
    }
    kwargs.update(overrides)
    writer = ResultWriter(tmp_path)
    path = writer.write(**kwargs)  # type: ignore[arg-type]
    assert path is not None and path.exists()
    return read_result(tmp_path)


def test_one_row_per_scored_company_ranked(tmp_path: Path) -> None:
    rows = _write(tmp_path)
    assert len(rows) == 2
    assert [r["company_id"] for r in rows] == [0, 1], "rows follow rank order"
    assert rows[0]["primary_score"] == 740


def test_task_identity_is_recorded(tmp_path: Path) -> None:
    """Without this a leaderboard row cannot be traced to a specific world."""
    rows = _write(tmp_path)
    expected = compute_task_instance(_SETTINGS, "bench-30min", "1")
    for row in rows:
        assert row["task_id"] == expected.task_id
        assert row["scenario_id"] == "bench-30min"
        assert row["scenario_version"] == "1"
        assert row["map_seed"] == 1001
        assert row["settings_digest"] == expected.settings_digest


def test_run_shape_is_recorded(tmp_path: Path) -> None:
    row = _write(tmp_path)[0]
    assert row["runtime_mode"] == "async_realtime"
    assert row["end_reason"] == "time_limit"
    assert row["wall_seconds"] == 1800.5
    assert row["game_days"] == 912
    assert row["start_game_date"] == 715_000


def test_contestant_detail_is_recorded(tmp_path: Path) -> None:
    rows = _write(tmp_path)
    scored = next(r for r in rows if r["company_id"] == 0)
    assert scored["agent_id"] == "road_agent"
    assert scored["model"] == "gpt-5.2"
    assert scored["total_actions"] == 42
    assert scored["total_cost_usd"] == 3.91
    assert scored["cost_is_estimated"] is False


def test_company_without_participant_still_scored(tmp_path: Path) -> None:
    """An AI opponent or unattended company has a score but no contestant."""
    rows = _write(tmp_path)
    unattended = next(r for r in rows if r["company_id"] == 1)
    assert unattended["primary_score"] == 380
    assert unattended["agent_id"] == ""
    assert unattended["model"] == ""


def test_git_provenance_is_recorded(tmp_path: Path) -> None:
    """The revision that produced a result must be identifiable."""
    row = _write(tmp_path)[0]
    assert row["nttd_git_sha"], "expected a git sha in a checkout"
    assert isinstance(row["nttd_git_dirty"], bool)
    assert row["recorded_at"] is not None


def test_gamescript_digest_recorded_when_present(tmp_path: Path) -> None:
    gs = tmp_path / "main.nut"
    gs.write_text("class NttdGS extends GSController {}")
    row = _write(tmp_path, gamescript_path=gs)[0]
    assert row["gamescript_digest"], "GameScript must be pinned"


def test_missing_gamescript_records_empty_not_crash(tmp_path: Path) -> None:
    """A partial record must be visibly partial, not a failure."""
    row = _write(tmp_path, gamescript_path=tmp_path / "absent.nut")[0]
    assert row["gamescript_digest"] == ""


def test_unseeded_run_records_sentinel_seed(tmp_path: Path) -> None:
    """An unseeded run is flagged as such rather than defaulting to a real seed."""
    settings = {k: v for k, v in _SETTINGS.items() if k != "_map_seed"}
    task = compute_task_instance(settings, "bench-30min", "1")
    row = _write(tmp_path, task=task)[0]
    assert row["map_seed"] == -1


def test_no_task_instance_records_empty_identity(tmp_path: Path) -> None:
    """A session started without a scenario still produces a readable record."""
    row = _write(tmp_path, task=None)[0]
    assert row["task_id"] == ""
    assert row["map_seed"] == -1
    assert row["primary_score"] == 740, "score is still recorded"


def test_no_scores_writes_nothing(tmp_path: Path) -> None:
    """A session with no active companies has no result to claim."""
    writer = ResultWriter(tmp_path)
    assert writer.write(
        session_id="ses_empty", scores=[], task=None, runtime_mode="heartbeat",
        end_reason="manual", wall_seconds=0.0, start_game_date=0, end_game_date=0,
    ) is None
    assert read_result(tmp_path) == []


def test_read_result_of_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_result(tmp_path / "nonexistent") == []


# ---------------------------------------------------------------------------
# Capability attestation
# ---------------------------------------------------------------------------


def test_clean_scored_run_is_attested(tmp_path: Path) -> None:
    """A scored run that stayed in the participant tier records that fact."""
    row = _write(tmp_path, capability={
        "scored": True, "clean_run": True,
        "blocked_attempts": 0, "blocked_operations": [],
    })[0]
    assert row["scored_session"] is True
    assert row["clean_run"] is True
    assert row["blocked_attempts"] == 0
    assert row["blocked_operations"] == ""


def test_blocked_attempt_is_recorded_without_voiding_the_score(tmp_path: Path) -> None:
    """The refusal means nothing happened, so the score stands and is flagged."""
    row = _write(tmp_path, capability={
        "scored": True, "clean_run": False,
        "blocked_attempts": 2,
        "blocked_operations": ["deity/change_balance", "rcon"],
    })[0]
    assert row["clean_run"] is False
    assert row["blocked_attempts"] == 2
    assert "deity/change_balance" in row["blocked_operations"]
    assert row["primary_score"] == 740, "the score is still recorded"


def test_unscored_run_is_marked_as_such(tmp_path: Path) -> None:
    """An unscored session had operator powers available all along."""
    row = _write(tmp_path, capability={
        "scored": False, "clean_run": True,
        "blocked_attempts": 0, "blocked_operations": [],
    })[0]
    assert row["scored_session"] is False


def test_missing_attestation_defaults_to_unscored(tmp_path: Path) -> None:
    """Absent information must not read as a stronger claim than was made."""
    row = _write(tmp_path)[0]
    assert row["scored_session"] is False


def test_capability_digest_reflects_the_vocabulary(tmp_path: Path) -> None:
    """Reclassifying an action must change the digest, so a verifier can tell
    that two results were not scored under the same rules.
    """
    from unittest.mock import patch

    from nttd.db import result_writer

    baseline = _write(tmp_path)[0]["capability_digest"]
    assert baseline

    with patch.object(result_writer, "KNOWN_ACTIONS", {"build_road_stop"}):
        changed = result_writer.capability_digest()
    assert changed != baseline
