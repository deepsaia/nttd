"""Load session data from logs/sessions/<session_id>/ into analysis-friendly structures.

Supports both completed sessions (merged parquet files) and in-progress
sessions (fragment files under _fragments/).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl
from pyhocon import ConfigFactory

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path("logs/sessions")

_PARQUET_TYPES = ("actions", "agent_cycles", "events", "snapshots", "tiles")


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

    # From agents.conf
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Parquet DataFrames
    actions: pd.DataFrame = field(default_factory=pd.DataFrame)
    agent_cycles: pd.DataFrame = field(default_factory=pd.DataFrame)
    events: pd.DataFrame = field(default_factory=pd.DataFrame)
    snapshots: pd.DataFrame = field(default_factory=pd.DataFrame)
    tiles: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def model(self) -> str:
        """LLM model used (from first agent entry)."""
        for agent in self.agents.values():
            return agent.get("model", "unknown")
        return "unknown"

    @property
    def duration_minutes(self) -> float:
        """Session duration in minutes (from timestamps)."""
        if self.started_at and self.ended_at:
            start = pd.Timestamp(self.started_at)
            end = pd.Timestamp(self.ended_at)
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


def load_fragments(session_dir: Path, parquet_type: str) -> pd.DataFrame:
    """Read all fragment files for a parquet type and concatenate into one DataFrame.

    Uses polars for fast parquet I/O, converts to pandas for compatibility
    with existing plot functions. Returns an empty DataFrame if no fragments exist.
    """
    fragments_dir = session_dir / "_fragments"
    if not fragments_dir.exists():
        return pd.DataFrame()

    pattern = f"{parquet_type}_*.parquet"
    fragment_paths = sorted(fragments_dir.glob(pattern))
    if not fragment_paths:
        return pd.DataFrame()

    frames: list[pl.DataFrame] = []
    for frag_path in fragment_paths:
        try:
            frames.append(pl.read_parquet(frag_path))
        except Exception:
            logger.warning("Failed to read fragment %s, skipping", frag_path)

    if not frames:
        return pd.DataFrame()

    return pl.concat(frames).to_pandas()


def _load_parquet_with_fragments(session_dir: Path, parquet_type: str) -> pd.DataFrame:
    """Load a parquet type, preferring merged file but falling back to fragments.

    Uses polars for fast parquet I/O. If the merged file exists, returns it.
    Otherwise reads fragments. Converts to pandas for compatibility with
    existing plot functions.
    """
    merged_path = session_dir / f"{parquet_type}.parquet"
    if merged_path.exists():
        try:
            return pl.read_parquet(merged_path).to_pandas()
        except Exception:
            logger.warning("Failed to read %s", merged_path)

    return load_fragments(session_dir, parquet_type)


def load_session(session_id: str, sessions_dir: Path | str = SESSIONS_DIR) -> SessionData:
    """Load all data for a session from its directory."""
    session_dir = Path(sessions_dir) / session_id
    if not session_dir.exists():
        raise FileNotFoundError(f"Session directory not found: {session_dir}")

    data = SessionData(session_id=session_id, session_dir=session_dir)

    # Load session.conf
    conf_path = session_dir / "session.conf"
    if conf_path.exists():
        conf = ConfigFactory.parse_file(str(conf_path))
        sess = conf.get("session", {})
        data.name = sess.get("name", session_id)
        data.status = sess.get("status", "")
        data.created_at = sess.get("created_at", "")
        data.started_at = sess.get("started_at", "")
        data.ended_at = sess.get("ended_at", "")
        data.end_reason = sess.get("end_reason", "")
        data.game_port = sess.get("game_port", 0)
        data.admin_port = sess.get("admin_port", 0)
        data.settings = dict(conf.get("settings", {}))

    # Load agents.conf
    agents_path = session_dir / "agents.conf"
    if agents_path.exists():
        agents_conf = ConfigFactory.parse_file(str(agents_path))
        agents_tree = agents_conf.get("agents", {})
        for agent_id in agents_tree:
            data.agents[agent_id] = dict(agents_tree[agent_id])

    # Load Parquet files (merged or fragments for in-progress sessions)
    for parquet_type in _PARQUET_TYPES:
        df = _load_parquet_with_fragments(session_dir, parquet_type)
        if not df.empty:
            setattr(data, parquet_type, df)

    # Tag DataFrames with session info for multi-session analysis
    for attr in ("actions", "agent_cycles", "events", "snapshots"):
        df = getattr(data, attr)
        if not df.empty:
            df["_session_id"] = session_id
            df["_model"] = data.model

    logger.info(
        "Loaded session %s: %d actions, %d cycles, %d events, %d snapshots",
        session_id, len(data.actions), len(data.agent_cycles),
        len(data.events), len(data.snapshots),
    )
    return data


def load_sessions(
    session_ids: list[str],
    sessions_dir: Path | str = SESSIONS_DIR,
) -> list[SessionData]:
    """Load multiple sessions."""
    return [load_session(sid, sessions_dir) for sid in session_ids]


def combine_dataframes(
    sessions: list[SessionData],
    attr: str,
) -> pd.DataFrame:
    """Concatenate a DataFrame attribute across multiple sessions."""
    frames = [getattr(s, attr) for s in sessions if not getattr(s, attr).empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _extract_json_field(json_str: str, field_path: str) -> Any:
    """Extract a nested field from a JSON string by dot-separated path."""
    try:
        data = json.loads(json_str)
        for key in field_path.split("."):
            data = data[key]
        return data
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def extract_snapshot_json(snapshots_df: pd.DataFrame, field_path: str) -> pd.Series:
    """Extract a nested field from snapshot_json column.

    Example: extract_snapshot_json(df, "companies") returns a Series of company lists.
    """
    return snapshots_df["snapshot_json"].apply(
        lambda s: _extract_json_field(s, field_path)
    )
