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

import hashlib
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from nttd.analysis.score import CompanyScore
from nttd.config.task_instance import TaskInstance, file_digest
from nttd.constants import KNOWN_ACTIONS, OPERATOR_ACTIONS

logger = logging.getLogger(__name__)

_RESULT_FILENAME = "result.parquet"

_SCHEMA = pa.schema([
    # Identity
    ("session_id", pa.string()),
    ("company_id", pa.int16()),
    ("company_name", pa.string()),
    # Score. One definition, so no version column: nttd_git_sha and gamescript_digest below
    # pin what produced these far more precisely than a hand-typed string ever did.
    #
    # performance_rating is RAW, including the game's -1 for a quarter it could not rate. It
    # used to be a clamped primary_score beside a rating_available flag, which recorded one
    # fact twice, the flag existing only to restore what the clamp destroyed.
    ("performance_rating", pa.int32()),
    # The run's delivered cargo, and what breaks a tie on equal ratings. One column: a
    # tiebreak_cargo beside an identical total_cargo is the same number under two names.
    ("total_cargo", pa.int64()),
    # Attributed per transport by the GameScript, which accounts it per vehicle because the
    # game reports cargo only company-wide. These four should sum to total_cargo; when they do
    # not, the attribution is wrong, and that is meant to be visible.
    ("rail_cargo", pa.int64()),
    ("road_cargo", pa.int64()),
    ("water_cargo", pa.int64()),
    ("air_cargo", pa.int64()),
    ("company_value", pa.int64()),
    ("final_balance", pa.int64()),
    ("final_loan", pa.int64()),
    # Task instance
    ("task_id", pa.string()),
    ("scenario_id", pa.string()),
    ("map_seed", pa.int64()),
    ("settings_digest", pa.string()),
    # The world settings a scored scenario is allowed to vary. They may differ
    # between scored runs only because they are disclosed here: a reader comparing
    # two rows needs to see that one was 512x512 mountainous.
    ("map_size_x", pa.int32()),
    ("map_size_y", pa.int32()),
    ("landscape", pa.string()),
    ("terrain_type", pa.string()),
    ("profile_version", pa.string()),
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
    # True when the contestant reported spend at all. Distinguishes "told us zero"
    # (a local RL policy that genuinely cost nothing) from "told us nothing", which a
    # reader comparing them needs and a single 0.0 cannot express.
    ("spend_is_reported", pa.bool_()),
    # Per-model spend as JSON. A multi-agent system routinely uses several models --
    # neuro-san runs a front-man plus specialists, often on different ones -- so a
    # single cost figure hides the shape of the system that produced it.
    ("model_breakdown_json", pa.string()),
    # Capability attestation. Self-hosting means auth cannot prevent cheating, so
    # the record states what the run actually stayed within. A scored run that
    # attempted an operator power is still scored -- the attempt was refused -- but
    # it is no longer a clean run, which is what makes an accident visible.
    ("scored_session", pa.bool_()),
    ("clean_run", pa.bool_()),
    ("blocked_attempts", pa.int32()),
    ("blocked_operations", pa.string()),
    ("capability_digest", pa.string()),
    ("nttd_git_sha", pa.string()),
    ("nttd_git_dirty", pa.bool_()),
    ("gamescript_digest", pa.string()),
    ("scenario_file_digest", pa.string()),
    # The savegame a verifier reloads to recompute the score. Empty means none was
    # captured, which is a verification gap rather than a detail: without it the
    # score is self-reported and cannot be checked by anyone.
    ("final_save_name", pa.string()),
    ("final_save_digest", pa.string()),
    ("final_save_bytes", pa.int64()),
    ("openttd_version", pa.string()),
    # Business metrics are deliberately NOT here. They are derived, still being refined, and
    # a public board should not be sorted on numbers whose definition is in flux. They are
    # computed for the monitor from the same artifacts, so nothing is lost by leaving them out
    # of the record a leaderboard reads.
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


def capability_digest() -> str:
    """Digest of the action vocabulary a contestant was permitted.

    Lets a verifier tell whether two results were scored under the same rules.
    Exposing a new action or reclassifying one changes this, so a leaderboard can
    detect that entries are no longer directly comparable.
    """
    payload = json.dumps(
        {
            "participant": sorted(KNOWN_ACTIONS),
            "operator": sorted(OPERATOR_ACTIONS),
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


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
        final_save: Path | None = None,
        openttd_binary: str = "",
        capability: dict[str, Any] | None = None,
        dimensions: dict[str, str] | None = None,
    ) -> Path | None:
        """Write result.parquet. Returns the path, or None if there is nothing to record.

        Args:
            scores: Ranked company scores from ``analysis.score.rank_companies``.
            task: Task instance identity, or None for a session without a scenario.
            participants: Per-company contestant detail, keyed by company_id.
            gamescript_path: The GameScript that ran, hashed for provenance.
            final_save: The captured savegame, hashed so a submitted bundle is
                tamper-evident. None when the capture failed.
            openttd_binary: Path to the OpenTTD binary, queried for its version.
            capability: Attestation from the session's scored lock -- whether the
                run was scored and whether it stayed within the participant tier.
            dimensions: The world settings a scored scenario is allowed to vary, in
                readable form. Recorded because they are permitted to differ only on
                condition of being disclosed: a reader comparing two rows needs to
                see that one was 512x512 mountainous.
        """
        if not scores:
            logger.warning("Session %s: no company scores, result.parquet not written", session_id)
            return None

        git_sha, git_dirty = _git_revision(self.repo_root)
        gs_digest = file_digest(gamescript_path) if gamescript_path else None
        save_digest = file_digest(final_save) if final_save else None
        save_bytes = final_save.stat().st_size if final_save and final_save.exists() else 0
        scenario_digest = file_digest(self.session_dir / "nttd_scenario.conf")
        version = openttd_version(openttd_binary) if openttd_binary else ""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        people = participants or {}

        # The capability set the run was allowed, hashed so a verifier can tell
        # whether two results were scored under the same rules.
        attest = capability or {}
        dims = dimensions or {}
        blocked_ops = attest.get("blocked_operations") or []

        rows: list[dict[str, Any]] = []
        for score in scores:
            who = people.get(score.company_id, {})
            rows.append({
                "session_id": session_id,
                "company_id": score.company_id,
                "company_name": score.company_name,
                "performance_rating": score.performance_rating,
                "total_cargo": score.total_cargo,
                "rail_cargo": score.rail_cargo,
                "road_cargo": score.road_cargo,
                "water_cargo": score.water_cargo,
                "air_cargo": score.air_cargo,
                "company_value": score.company_value,
                "final_balance": score.balance,
                "final_loan": score.loan,
                "task_id": task.task_id if task else "",
                "scenario_id": task.scenario_id if task else "",
                "map_seed": task.seed if (task and task.seed is not None) else -1,
                "settings_digest": task.settings_digest if task else "",
                # The permitted-to-vary dimensions, as leaderboard columns.
                "map_size_x": int(dims.get("size_x", 0) or 0),
                "map_size_y": int(dims.get("size_y", 0) or 0),
                "landscape": dims.get("landscape", ""),
                "terrain_type": dims.get("terrain_type", ""),
                "profile_version": dims.get("profile_version", ""),
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
                "spend_is_reported": bool(who.get("spend_is_reported", False)),
                "model_breakdown_json": json.dumps(
                    who.get("model_breakdown") or [], separators=(",", ":"),
                ),
                "scored_session": bool(attest.get("scored", False)),
                "clean_run": bool(attest.get("clean_run", True)),
                "blocked_attempts": int(attest.get("blocked_attempts", 0)),
                "blocked_operations": ",".join(blocked_ops),
                "capability_digest": capability_digest(),
                "nttd_git_sha": git_sha,
                "nttd_git_dirty": git_dirty,
                "gamescript_digest": gs_digest or "",
                "scenario_file_digest": scenario_digest or "",
                "final_save_name": final_save.name if final_save else "",
                "final_save_digest": save_digest or "",
                "final_save_bytes": save_bytes,
                "openttd_version": version,
                "recorded_at": now,
            })

        self.session_dir.mkdir(parents=True, exist_ok=True)
        path = self.session_dir / _RESULT_FILENAME
        table = pa.Table.from_pylist(rows, schema=_SCHEMA)
        pq.write_table(table, path, compression="zstd")
        logger.info(
            "Session %s: wrote %s (%d row(s), task_id=%s)",
            session_id, path, len(rows), task.task_id if task else "none",
        )
        return path


def read_result(session_dir: Path) -> list[dict[str, Any]]:
    """Read a session's result rows, or [] if none were written.

    Columns the file predates are filled with a typed default rather than left absent.
    Every result written before a column existed is missing it, and readers index rows
    directly: ``nttd result`` raised ``KeyError: 'final_save_digest'`` on a session from
    two days earlier, and adding the business metrics made every existing file old in
    the same way. A board ingesting bundles from a range of nttd versions would hit this
    constantly, so it is fixed once here rather than at each reader.
    """
    path = Path(session_dir) / _RESULT_FILENAME
    if not path.exists():
        return []

    rows = pq.read_table(path).to_pylist()
    for row in rows:
        for field in _SCHEMA:
            if field.name not in row:
                row[field.name] = _default_for(field.type)
    return rows


def _default_for(arrow_type: pa.DataType) -> Any:
    """An empty value of the right type, so a missing column reads as absent.

    Not None: a reader formatting a number would then have to guard every field, and
    the point is that it does not have to.
    """
    if pa.types.is_boolean(arrow_type):
        return False
    if pa.types.is_floating(arrow_type):
        return 0.0
    if pa.types.is_integer(arrow_type):
        return 0
    if pa.types.is_timestamp(arrow_type):
        return None
    return ""
