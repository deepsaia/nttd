"""HOCON config writer for session metadata and agent connection data.

Writes session.conf and agents.conf files under each session's log directory.
Uses pyhocon for parsing and manual formatting for output (pyhocon's writer
is limited, so we use a simple key=value approach).
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _quote(value: Any) -> str:
    """Format a value for HOCON output."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if value is None:
        return "null"
    return f'"{value}"'


def _write_block(lines: list[str], indent: str, key: str, data: dict[str, Any]) -> None:
    """Write a HOCON block with key = value pairs."""
    lines.append(f"{indent}{key} {{")
    inner = indent + "  "
    for k, v in data.items():
        if isinstance(v, dict):
            _write_block(lines, inner, k, v)
        else:
            lines.append(f"{inner}{k} = {_quote(v)}")
    lines.append(f"{indent}}}")


def write_session_conf(
    session_dir: Path,
    session_id: str,
    name: str = "",
    status: str = "active",
    created_at: str | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    end_reason: str | None = None,
    game_port: int | None = None,
    admin_port: int | None = None,
    pid: int | None = None,
    settings: dict[str, str] | None = None,
    meta: dict[str, Any] | None = None,
) -> Path:
    """Write or overwrite session.conf with current session state."""
    session_dir.mkdir(parents=True, exist_ok=True)
    conf_path = session_dir / "session.conf"

    lines: list[str] = []

    session_data: dict[str, Any] = {
        "id": session_id,
        "name": name,
        "status": status,
    }
    if created_at:
        session_data["created_at"] = created_at
    if started_at:
        session_data["started_at"] = started_at
    if ended_at:
        session_data["ended_at"] = ended_at
    if end_reason:
        session_data["end_reason"] = end_reason
    if game_port is not None:
        session_data["game_port"] = game_port
    if admin_port is not None:
        session_data["admin_port"] = admin_port
    if pid is not None:
        session_data["pid"] = pid

    _write_block(lines, "", "session", session_data)

    if settings:
        lines.append("")
        settings_block: dict[str, Any] = {}
        for k, v in settings.items():
            settings_block[f'"{k}"'] = v
        lines.append("settings {")
        for k, v in settings.items():
            lines.append(f'  "{k}" = {_quote(v)}')
        lines.append("}")

    if meta:
        lines.append("")
        _write_block(lines, "", "meta", meta)

    lines.append("")
    conf_path.write_text("\n".join(lines))
    logger.debug("Wrote session.conf: %s", conf_path)
    return conf_path


def update_session_conf(
    session_dir: Path,
    updates: dict[str, Any],
) -> None:
    """Update specific fields in session.conf by reading, modifying, and rewriting.

    For simplicity, reads the existing conf with pyhocon, merges updates,
    and rewrites. Updates should be flat keys like 'session.status' or
    'session.ended_at'.
    """
    conf_path = session_dir / "session.conf"
    if not conf_path.exists():
        logger.warning("Cannot update session.conf -- file not found: %s", conf_path)
        return

    try:
        from pyhocon import ConfigFactory
        config = ConfigFactory.parse_file(str(conf_path))

        # Apply updates (dot-separated paths)
        for key, value in updates.items():
            parts = key.split(".")
            node = config
            for part in parts[:-1]:
                if part not in node:
                    node[part] = {}
                node = node[part]
            node[parts[-1]] = value

        # Rewrite the file
        _rewrite_conf_from_tree(conf_path, config)
        logger.debug("Updated session.conf: %s (keys: %s)", conf_path, list(updates.keys()))
    except ImportError:
        logger.warning("pyhocon not installed -- cannot update session.conf")
    except Exception:
        logger.exception("Failed to update session.conf at %s", conf_path)


def write_agents_conf(
    session_dir: Path,
    agents: dict[str, dict[str, Any]],
) -> Path:
    """Write or overwrite agents.conf with current agent connection data."""
    session_dir.mkdir(parents=True, exist_ok=True)
    conf_path = session_dir / "agents.conf"

    lines: list[str] = ["agents {"]
    for agent_id, agent_data in agents.items():
        lines.append(f'  "{agent_id}" {{')
        for k, v in agent_data.items():
            lines.append(f"    {k} = {_quote(v)}")
        lines.append("  }")
    lines.append("}")
    lines.append("")

    conf_path.write_text("\n".join(lines))
    logger.debug("Wrote agents.conf: %s", conf_path)
    return conf_path


def update_agent_in_conf(
    session_dir: Path,
    agent_id: str,
    agent_data: dict[str, Any],
) -> None:
    """Add or update a single agent entry in agents.conf."""
    conf_path = session_dir / "agents.conf"

    # Read existing agents
    existing: dict[str, dict[str, Any]] = {}
    if conf_path.exists():
        try:
            from pyhocon import ConfigFactory
            config = ConfigFactory.parse_file(str(conf_path))
            agents_tree = config.get("agents", {})
            for aid in agents_tree:
                existing[aid] = dict(agents_tree[aid])
        except Exception:
            logger.warning("Failed to parse existing agents.conf, overwriting")

    # Merge update
    if agent_id in existing:
        existing[agent_id].update(agent_data)
    else:
        existing[agent_id] = agent_data

    write_agents_conf(session_dir, existing)


def read_session_conf(session_dir: Path) -> dict[str, Any] | None:
    """Read session.conf and return parsed data, or None if not found."""
    conf_path = session_dir / "session.conf"
    if not conf_path.exists():
        return None

    try:
        from pyhocon import ConfigFactory
        config = ConfigFactory.parse_file(str(conf_path))
        result: dict[str, Any] = {}

        # Session block
        session = config.get("session", {})
        for key in session:
            result[key] = session[key]
        # Rename 'id' to 'session_id' for API consistency
        if "id" in result and "session_id" not in result:
            result["session_id"] = result.pop("id")

        # Settings block (keys are stored quoted, strip surrounding quotes)
        settings = config.get("settings", {})
        if settings:
            result["settings"] = {k.strip('"'): v for k, v in dict(settings).items()}

        # Meta block
        meta = config.get("meta", {})
        if meta:
            result["meta"] = dict(meta)

        return result
    except ImportError:
        logger.warning("pyhocon not installed -- cannot read session.conf")
        return None
    except Exception:
        logger.exception("Failed to read session.conf at %s", conf_path)
        return None


def read_agents_conf(session_dir: Path) -> dict[str, dict[str, Any]]:
    """Read agents.conf and return dict of agent_id -> agent_data."""
    conf_path = session_dir / "agents.conf"
    if not conf_path.exists():
        return {}

    try:
        from pyhocon import ConfigFactory
        config = ConfigFactory.parse_file(str(conf_path))
        agents_tree = config.get("agents", {})
        result: dict[str, dict[str, Any]] = {}
        for aid in agents_tree:
            result[aid] = dict(agents_tree[aid])
        return result
    except ImportError:
        logger.warning("pyhocon not installed -- cannot read agents.conf")
        return {}
    except Exception:
        logger.exception("Failed to read agents.conf at %s", conf_path)
        return {}


def _rewrite_conf_from_tree(conf_path: Path, config: Any) -> None:
    """Rewrite a conf file from a pyhocon ConfigTree."""
    lines: list[str] = []
    _tree_to_lines(lines, "", config)
    lines.append("")
    conf_path.write_text("\n".join(lines))


def _tree_to_lines(lines: list[str], indent: str, node: Any) -> None:
    """Recursively convert a pyhocon ConfigTree to HOCON lines."""
    for key in node:
        value = node[key]
        # Check if value is a config tree (dict-like)
        if hasattr(value, "__iter__") and hasattr(value, "get") and not isinstance(value, str):
            lines.append(f"{indent}{key} {{")
            _tree_to_lines(lines, indent + "  ", value)
            lines.append(f"{indent}}}")
        else:
            lines.append(f"{indent}{key} = {_quote(value)}")
