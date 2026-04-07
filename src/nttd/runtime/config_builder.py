"""Build per-session OpenTTD config directories.

Each session gets its own config directory with patched ports and
symlinked shared resources (game scripts, AI, basesets).
"""

import logging
import os
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def _patch_ini_value(content: str, key: str, value: str) -> str:
    """Replace an INI-style key = value line, preserving surrounding content."""
    pattern = re.compile(rf"^({re.escape(key)}\s*=\s*).*$", re.MULTILINE)
    if pattern.search(content):
        return pattern.sub(rf"\g<1>{value}", content)
    # Key not found — append to end
    return content + f"\n{key} = {value}\n"


def build_session_config(
    base_config_dir: Path,
    session_dir: Path,
    game_port: int,
    admin_port: int,
    admin_password: str,
    settings: dict[str, str] | None = None,
    ai_opponents: int = 0,
    agent_companies: int = 0,
) -> Path:
    """Create a per-session OpenTTD config directory.

    Game settings are baked into openttd.cfg so the initial map generation
    uses them — no ``newgame`` RCON needed (which would break the GameScript).

    Args:
        base_config_dir: Template config directory (e.g. ottd_config/).
        session_dir: Target directory for this session (e.g. runs/ses_abc123/).
        game_port: Game port for player connections.
        admin_port: Admin port for nttd control.
        admin_password: Password for admin port authentication.
        settings: Game settings to bake into the config (key=value pairs).
        ai_opponents: Number of AI opponent companies to configure.
        agent_companies: Number of idle company slots for nttd agents.

    Returns:
        Path to the session config directory.
    """
    session_dir.mkdir(parents=True, exist_ok=True)

    # --- openttd.cfg: copy and patch ports + game settings ---
    src_cfg = base_config_dir / "openttd.cfg"
    dst_cfg = session_dir / "openttd.cfg"
    cfg_content = src_cfg.read_text()
    cfg_content = _patch_ini_value(cfg_content, "server_port", str(game_port))
    cfg_content = _patch_ini_value(cfg_content, "server_admin_port", str(admin_port))

    # Bake game settings into the config
    total_companies = ai_opponents + agent_companies
    if total_companies > 0:
        cfg_content = _patch_ini_value(cfg_content, "ai_in_multiplayer", "true")
        cfg_content = _patch_ini_value(cfg_content, "max_no_competitors", str(total_companies))
        cfg_content = _patch_ini_value(cfg_content, "competitors_interval", "0")

    for key, value in (settings or {}).items():
        cfg_content = _patch_ini_value(cfg_content, key, value)

    dst_cfg.write_text(cfg_content)

    # --- secrets.cfg: copy and patch, or generate from scratch ---
    src_secrets = base_config_dir / "secrets.cfg"
    dst_secrets = session_dir / "secrets.cfg"
    if src_secrets.exists():
        secrets_content = src_secrets.read_text()
        secrets_content = _patch_ini_value(secrets_content, "admin_password", admin_password)
    else:
        secrets_content = (
            "[network]\n"
            "server_password = \n"
            "rcon_password = \n"
            f"admin_password = {admin_password}\n"
        )
    dst_secrets.write_text(secrets_content)

    # --- private.cfg: copy if exists (not required, OpenTTD generates defaults) ---
    src_private = base_config_dir / "private.cfg"
    if src_private.exists():
        shutil.copy2(src_private, session_dir / "private.cfg")

    # --- Symlink shared directories ---
    symlink_dirs = ["game", "ai", "scripts"]
    for dirname in symlink_dirs:
        src = base_config_dir / dirname
        dst = session_dir / dirname
        if src.exists() and not dst.exists():
            os.symlink(src.resolve(), dst)

    # --- Create session-specific directories ---
    for dirname in ["save", "scenario", "screenshot"]:
        (session_dir / dirname).mkdir(exist_ok=True)

    logger.info(
        "Built session config: %s (game_port=%d, admin_port=%d)",
        session_dir,
        game_port,
        admin_port,
    )
    return session_dir
