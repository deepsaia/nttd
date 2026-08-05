"""Load session data from logs/sessions/<session_id>/ into analysis-friendly structures.

Supports both completed sessions (merged parquet files) and in-progress
sessions (fragment files under _fragments/).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from nttd.db import parquet_reader, session_paths
from nttd.db.conf_writer import read_session_conf

logger = logging.getLogger(__name__)

# "result" is included so a report can reach the contestant detail and per-model
# spend that POST /report supplies; "agent_cycles" is gone with the gameloop.
_PARQUET_TYPES = ("actions", "events", "snapshots", "tiles", "result")


@dataclass
class SessionData:
    """All data for a single session, loaded from disk."""

    session_id: str
    session_dir: Path

    # From session.conf
    name: str = ""
    status: str = ""
    created_at: str = ""
    started_at: str = ""
    ended_at: str = ""
    end_reason: str = ""
    game_port: int = 0
    admin_port: int = 0
    settings: dict[str, str] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    # Contestant detail, from result.parquet. Was agents.conf, which the deleted
    # server-driven gameloop wrote and nothing writes now.
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Polars DataFrames
    actions: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())
    result: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())
    events: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())
    snapshots: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())
    tiles: pl.DataFrame = field(default_factory=lambda: pl.DataFrame())

    @property
    def config_name(self) -> str:
        """Scenario config name (filename stem from meta.config_path)."""
        cp = self.meta.get("config_path", "")
        if cp:
            return Path(cp).stem
        return ""

    @property
    def model(self) -> str:
        """The model or models that played, as the contestant reported them.

        From result.parquet rather than agents.conf: nttd runs no agent, so it never
        observes a model name and can only record what POST /report told it. A
        multi-agent entry reports several, joined with "+", so this can name more than
        one model -- which is the honest answer for a system that used more than one.
        """
        if not self.result.is_empty() and "model" in self.result.columns:
            reported = [m for m in self.result["model"].to_list() if m]
            if reported:
                return reported[0]
        return "unknown"

    @property
    def duration_minutes(self) -> float:
        """Session duration in minutes (from timestamps).

        For in-progress sessions (no ended_at), uses current UTC time.
        """
        if self.started_at:
            start = datetime.fromisoformat(self.started_at)
            if self.ended_at:
                end = datetime.fromisoformat(self.ended_at)
            else:
                end = datetime.now(tz=timezone.utc)
            return (end - start).total_seconds() / 60
        return 0.0

    @property
    def is_in_progress(self) -> bool:
        """True if session has unmerged fragments (still running or stopped uncleanly)."""
        fragments_dir = self.session_dir / "_fragments"
        return fragments_dir.exists() and any(fragments_dir.iterdir())

    @property
    def label(self) -> str:
        """Short label for plots: name (model)."""
        return f"{self.name} ({self.model})"


def load_frame(
    session_id: str,
    parquet_type: str,
    sessions_dir: Path | str | None = None,
) -> pl.DataFrame:
    """Load one parquet type for a session as a polars DataFrame.

    Merged file or unmerged fragments, whichever the session has: that choice belongs
    to db.parquet_reader, which the API repositories read through as well, so a live
    session looks the same from either side.
    """
    table = parquet_reader.read_table(session_id, parquet_type, sessions_dir=sessions_dir)
    if table is None:
        return pl.DataFrame()
    return pl.from_arrow(table)


def load_session(session_id: str, sessions_dir: Path | str | None = None) -> SessionData:
    """Load all data for a session from its directory."""
    root = Path(sessions_dir) if sessions_dir is not None else session_paths.sessions_dir()
    session_dir = root / session_id
    if not session_dir.exists():
        raise FileNotFoundError(f"Session directory not found: {session_dir}")

    data = SessionData(session_id=session_id, session_dir=session_dir)

    sess = read_session_conf(session_dir)
    if sess:
        data.name = sess.get("name", session_id)
        data.status = sess.get("status", "")
        data.created_at = sess.get("created_at", "")
        data.started_at = sess.get("started_at", "")
        data.ended_at = sess.get("ended_at", "")
        data.end_reason = sess.get("end_reason", "")
        data.game_port = sess.get("game_port", 0)
        data.admin_port = sess.get("admin_port", 0)
        data.settings = sess.get("settings", {})
        data.meta = sess.get("meta", {})


    # Load Parquet files (merged or fragments for in-progress sessions)
    for parquet_type in _PARQUET_TYPES:
        df = load_frame(session_id, parquet_type, sessions_dir=root)
        if not df.is_empty():
            setattr(data, parquet_type, df)

    # Tag DataFrames with session info for multi-session analysis
    for attr in ("actions", "events", "snapshots"):
        df = getattr(data, attr)
        if not df.is_empty():
            tagged = df.with_columns(
                pl.lit(session_id).alias("_session_id"),
                pl.lit(data.model).alias("_model"),
            )
            setattr(data, attr, tagged)

    logger.info(
        "Loaded session %s: %d actions, %d events, %d snapshots",
        session_id, len(data.actions),
        len(data.events), len(data.snapshots),
    )
    return data


def load_sessions(
    session_ids: list[str],
    sessions_dir: Path | str | None = None,
) -> list[SessionData]:
    """Load multiple sessions."""
    return [load_session(sid, sessions_dir) for sid in session_ids]


def combine_dataframes(
    sessions: list[SessionData],
    attr: str,
) -> pl.DataFrame:
    """Concatenate a DataFrame attribute across multiple sessions."""
    frames = [getattr(s, attr) for s in sessions if not getattr(s, attr).is_empty()]
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames)


def _extract_json_field(json_str: str, field_path: str) -> Any:
    """Extract a nested field from a JSON string by dot-separated path."""
    try:
        data = json.loads(json_str)
        for key in field_path.split("."):
            data = data[key]
        return data
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def extract_snapshot_json(snapshots_df: pl.DataFrame, field_path: str) -> pl.Series:
    """Extract a nested field from snapshot_json column.

    Example: extract_snapshot_json(df, "companies") returns a Series of extracted values.
    """
    return snapshots_df["snapshot_json"].map_elements(
        lambda s: _extract_json_field(s, field_path),
        return_dtype=pl.Object,
    )
