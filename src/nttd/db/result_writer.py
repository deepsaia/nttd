"""Writes result.parquet -- the immutable, provenanced record of a scored run.

One row per scored company, written once when a session ends. This is the artifact
a leaderboard ingests and a verifier checks, so it must capture everything needed
to answer "what exactly produced this number":

  * the score and the version of the definition that produced it
  * the task instance (which world, which rules) and the seed
  * the code that ran: nttd git revision, GameScript digest, OpenTTD build
  * the contestant: framework, model, and what it spent

Anything absent is recorded as absent rather than guessed, so a partial record is
visibly partial instead of quietly wrong.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from nttd.analysis.score import SCORE_VERSION, CompanyScore
from nttd.config.task_instance import TaskInstance, file_digest

logger = logging.getLogger(__name__)

_RESULT_FILENAME = "result.parquet"

_SCHEMA = pa.schema([
    # Identity
    ("session_id", pa.string()),
    ("company_id", pa.int16()),
    ("company_name", pa.string()),
    # Score
    ("score_version", pa.string()),
    ("primary_score", pa.int32()),
    ("tiebreak_cargo", pa.int64()),
    ("rating_available", pa.bool_()),
    ("company_value", pa.int64()),
    ("final_balance", pa.int64()),
    ("final_loan", pa.int64()),
    # Task instance
    ("task_id", pa.string()),
    ("scenario_id", pa.string()),
    ("scenario_version", pa.string()),
    ("map_seed", pa.int64()),
    ("settings_digest", pa.string()),
    # Run shape
    ("runtime_mode", pa.string()),
    ("end_reason", pa.string()),
    ("wall_seconds", pa.float64()),
    ("game_days", pa.int32()),
    ("start_game_date", pa.int32()),
    ("end_game_date", pa.int32()),
    # Contestant
    ("participant_type", pa.string()),
    ("agent_id", pa.string()),
    ("nttd_framework", pa.string()),
    ("model", pa.string()),
    ("total_actions", pa.int32()),
    ("successful_actions", pa.int32()),
    ("prompt_tokens", pa.int64()),
    ("completion_tokens", pa.int64()),
    ("total_cost_usd", pa.float64()),
    ("cost_is_estimated", pa.bool_()),
    # Provenance of the code that ran
    ("nttd_git_sha", pa.string()),
    ("nttd_git_dirty", pa.bool_()),
    ("gamescript_digest", pa.string()),
    ("scenario_file_digest", pa.string()),
    ("openttd_version", pa.string()),
    ("recorded_at", pa.timestamp("us")),
])


def _git_revision(repo_root: Path) -> tuple[str, bool]:
    """Return (short sha, dirty). Empty sha if this is not a git checkout.

    The dirty flag matters: a result produced from uncommitted code cannot be
    reproduced from the recorded revision alone.
    """
    try:
        sha = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        return sha, bool(status)
    except (subprocess.SubprocessError, OSError):
        logger.debug("Could not read git revision at %s", repo_root)
        return "", False


def openttd_version(binary: str) -> str:
    """Query the OpenTTD binary for its version string, or return ''."""
    try:
        out = subprocess.run(
            [binary, "--help"], capture_output=True, text=True, timeout=20,
        )
        first = (out.stdout or out.stderr).strip().splitlines()
        return first[0].strip() if first else ""
    except (subprocess.SubprocessError, OSError):
        logger.debug("Could not read OpenTTD version from %s", binary)
        return ""


class ResultWriter:
    """Builds and writes a session's result.parquet."""

    def __init__(self, session_dir: Path, repo_root: Path | None = None) -> None:
        self.session_dir = session_dir
        self.repo_root = repo_root or Path(__file__).resolve().parents[3]

    def write(
        self,
        session_id: str,
        scores: list[CompanyScore],
        task: TaskInstance | None,
        runtime_mode: str,
        end_reason: str,
        wall_seconds: float,
        start_game_date: int,
        end_game_date: int,
        participants: dict[int, dict[str, Any]] | None = None,
        gamescript_path: Path | None = None,
        openttd_binary: str = "",
    ) -> Path | None:
        """Write result.parquet. Returns the path, or None if there is nothing to record.

        Args:
            scores: Ranked company scores from ``analysis.score.rank_companies``.
            task: Task instance identity, or None for a session without a scenario.
            participants: Per-company contestant detail, keyed by company_id.
            gamescript_path: The GameScript that ran, hashed for provenance.
            openttd_binary: Path to the OpenTTD binary, queried for its version.
        """
        if not scores:
            logger.warning("Session %s: no company scores, result.parquet not written", session_id)
            return None

        git_sha, git_dirty = _git_revision(self.repo_root)
        gs_digest = file_digest(gamescript_path) if gamescript_path else None
        scenario_digest = file_digest(self.session_dir / "nttd_scenario.conf")
        version = openttd_version(openttd_binary) if openttd_binary else ""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        people = participants or {}

        rows: list[dict[str, Any]] = []
        for score in scores:
            who = people.get(score.company_id, {})
            rows.append({
                "session_id": session_id,
                "company_id": score.company_id,
                "company_name": score.company_name,
                "score_version": score.score_version,
                "primary_score": score.primary,
                "tiebreak_cargo": score.tiebreak,
                "rating_available": score.rating_available,
                "company_value": score.company_value,
                "final_balance": score.balance,
                "final_loan": score.loan,
                "task_id": task.task_id if task else "",
                "scenario_id": task.scenario_id if task else "",
                "scenario_version": task.scenario_version if task else "",
                "map_seed": task.seed if (task and task.seed is not None) else -1,
                "settings_digest": task.settings_digest if task else "",
                "runtime_mode": runtime_mode,
                "end_reason": end_reason,
                "wall_seconds": round(wall_seconds, 2),
                "game_days": max(end_game_date - start_game_date, 0),
                "start_game_date": start_game_date,
                "end_game_date": end_game_date,
                "participant_type": who.get("participant_type", "agent"),
                "agent_id": who.get("agent_id", ""),
                "nttd_framework": who.get("nttd_framework", ""),
                "model": who.get("model", ""),
                "total_actions": int(who.get("total_actions", 0)),
                "successful_actions": int(who.get("successful_actions", 0)),
                "prompt_tokens": int(who.get("prompt_tokens", 0)),
                "completion_tokens": int(who.get("completion_tokens", 0)),
                "total_cost_usd": float(who.get("total_cost", 0.0)),
                "cost_is_estimated": bool(who.get("cost_is_estimated", False)),
                "nttd_git_sha": git_sha,
                "nttd_git_dirty": git_dirty,
                "gamescript_digest": gs_digest or "",
                "scenario_file_digest": scenario_digest or "",
                "openttd_version": version,
                "recorded_at": now,
            })

        self.session_dir.mkdir(parents=True, exist_ok=True)
        path = self.session_dir / _RESULT_FILENAME
        table = pa.Table.from_pylist(rows, schema=_SCHEMA)
        pq.write_table(table, path, compression="zstd")
        logger.info(
            "Session %s: wrote %s (%d row(s), score_version=%s, task_id=%s)",
            session_id, path, len(rows), SCORE_VERSION, task.task_id if task else "none",
        )
        return path


def read_result(session_dir: Path) -> list[dict[str, Any]]:
    """Read a session's result rows, or [] if none were written."""
    path = Path(session_dir) / _RESULT_FILENAME
    if not path.exists():
        return []
    return pq.read_table(path).to_pylist()
