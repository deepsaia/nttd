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
) -> Path:
    """Create a per-session OpenTTD config directory.

    Args:
        base_config_dir: Template config directory (e.g. ottd_config/).
        session_dir: Target directory for this session (e.g. runs/ses_abc123/).
        game_port: Game port for player connections.
        admin_port: Admin port for nttd control.
        admin_password: Password for admin port authentication.

    Returns:
        Path to the session config directory.
    """
    session_dir.mkdir(parents=True, exist_ok=True)

    # --- openttd.cfg: copy and patch ports ---
    src_cfg = base_config_dir / "openttd.cfg"
    dst_cfg = session_dir / "openttd.cfg"
    cfg_content = src_cfg.read_text()
    cfg_content = _patch_ini_value(cfg_content, "server_port", str(game_port))
    cfg_content = _patch_ini_value(cfg_content, "server_admin_port", str(admin_port))
    dst_cfg.write_text(cfg_content)

    # --- secrets.cfg: copy and patch admin password ---
    src_secrets = base_config_dir / "secrets.cfg"
    dst_secrets = session_dir / "secrets.cfg"
    if src_secrets.exists():
        secrets_content = src_secrets.read_text()
        secrets_content = _patch_ini_value(secrets_content, "admin_password", admin_password)
        dst_secrets.write_text(secrets_content)

    # --- private.cfg: copy as-is ---
    src_private = base_config_dir / "private.cfg"
    if src_private.exists():
        shutil.copy2(src_private, session_dir / "private.cfg")

    # --- Symlink shared directories ---
    symlink_dirs = ["game", "ai", "baseset", "newgrf", "content_download", "scripts"]
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
