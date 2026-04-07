"""Load session data from logs/sessions/<session_id>/ into analysis-friendly structures."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
from pyhocon import ConfigFactory

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path("logs/sessions")


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
    def label(self) -> str:
        """Short label for plots: name (model)."""
        return f"{self.name} ({self.model})"


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

    # Load Parquet files
    for attr, filename in [
        ("actions", "actions.parquet"),
        ("agent_cycles", "agent_cycles.parquet"),
        ("events", "events.parquet"),
        ("snapshots", "snapshots.parquet"),
        ("tiles", "tiles.parquet"),
    ]:
        parquet_path = session_dir / filename
        if parquet_path.exists():
            try:
                table = pq.read_table(parquet_path)
                setattr(data, attr, table.to_pandas())
            except Exception:
                logger.warning("Failed to read %s", parquet_path)

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


def extract_snapshot_json(snapshots_df: pd.DataFrame, field_path: str) -> pd.Series:
    """Extract a nested field from snapshot_json column.

    Example: extract_snapshot_json(df, "companies") returns a Series of company lists.
    """
    def _extract(json_str: str) -> Any:
        try:
            data = json.loads(json_str)
            for key in field_path.split("."):
                data = data[key]
            return data
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    return snapshots_df["snapshot_json"].apply(_extract)
