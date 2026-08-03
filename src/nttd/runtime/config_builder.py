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
    """Replace an INI-style key = value line, preserving surrounding content.

    Supports section-qualified keys like ``game_creation.map_x`` which means
    key ``map_x`` inside the ``[game_creation]`` section.  Falls back to a
    global (section-unaware) match when no dot is present.
    """
    if "." in key and not key.startswith("_"):
        section, bare_key = key.split(".", 1)
        return _patch_ini_value_in_section(content, section, bare_key, value)

    pattern = re.compile(rf"^({re.escape(key)}\s*=\s*).*$", re.MULTILINE)
    if pattern.search(content):
        return pattern.sub(rf"\g<1>{value}", content)
    # Key not found -- append to end
    return content + f"\n{key} = {value}\n"


def _patch_ini_value_in_section(content: str, section: str, key: str, value: str) -> str:
    """Patch *key* inside ``[section]``.  Adds the key if missing."""
    lines = content.split("\n")
    section_header = f"[{section}]"
    in_section = False
    key_pattern = re.compile(rf"^({re.escape(key)}\s*=\s*).*$")
    patched = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == section_header:
            in_section = True
            continue
        if in_section and stripped.startswith("["):
            # Entered next section without finding key -- insert before this line
            if not patched:
                lines.insert(i, f"{key} = {value}")
                patched = True
            break
        if in_section and key_pattern.match(stripped):
            lines[i] = key_pattern.sub(rf"\g<1>{value}", line)
            patched = True
            break

    if not patched:
        # Section exists but key not found (section was last in file)
        if in_section:
            lines.append(f"{key} = {value}")
        else:
            # Section doesn't exist -- create it
            lines.append(f"\n{section_header}")
            lines.append(f"{key} = {value}")

    return "\n".join(lines)


def _snapshot_scenario(source: Path, destination: Path) -> None:
    """Write the FULLY RESOLVED scenario to the session directory.

    Resolved rather than copied, because benchmark scenarios use HOCON ``include``
    to share the locked world settings. A plain copy preserves the include LINE but
    not the included file, so the snapshot became a pointer to something outside the
    session directory. Reparsing it then failed the include, and ``load`` treats a
    parse failure as "use defaults" -- which silently reported starting_year 1960 for
    a run that was actually generated at 2020. The provenance record has to stand
    alone, since its whole purpose is to survive the source files being edited or
    moved.

    Falls back to a byte copy when the config cannot be parsed or re-serialised: an
    unfaithful snapshot is worth more than none, and the caller has already validated
    the config it is running.
    """
    if not source.is_file():
        logger.warning("Scenario path %s is not a file -- not snapshotted", source)
        return

    try:
        from pyhocon import ConfigFactory
        from pyhocon.converter import HOCONConverter

        resolved = ConfigFactory.parse_file(str(source))
        destination.write_text(HOCONConverter.to_hocon(resolved) + "\n")
    except Exception:
        logger.exception(
            "Could not resolve scenario %s for the provenance snapshot -- copying it "
            "verbatim, so any HOCON include it uses will not be captured", source,
        )
        shutil.copy2(source, destination)


def build_session_config(
    base_config_dir: Path,
    session_dir: Path,
    game_port: int,
    admin_port: int,
    admin_password: str,
    settings: dict[str, str] | None = None,
    ai_opponents: int = 0,
    agent_companies: int = 0,
    scenario_path: Path | str | None = None,
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
        scenario_path: The scenario file this session was built from. Copied into
            the session directory so the run stays verifiable even if the source
            file is later edited or moved.

    Returns:
        Path to the session config directory.
    """
    session_dir.mkdir(parents=True, exist_ok=True)

    # --- nttd_scenario.conf: snapshot the resolved scenario for provenance ---
    # Named distinctly from OpenTTD's own scenario/ directory, which is transient
    # and removed on cleanup.
    if scenario_path:
        _snapshot_scenario(Path(scenario_path), session_dir / "nttd_scenario.conf")

    # --- openttd.cfg: copy and patch ports + game settings ---
    src_cfg = base_config_dir / "openttd.cfg"
    dst_cfg = session_dir / "openttd.cfg"
    cfg_content = src_cfg.read_text()
    cfg_content = _patch_ini_value(cfg_content, "server_port", str(game_port))
    cfg_content = _patch_ini_value(cfg_content, "server_admin_port", str(admin_port))

    # Bake game settings into the config (from scenario HOCON).
    #
    # Keys prefixed with "_" are nttd-internal runtime metadata (_runtime_mode,
    # _map_seed, _ec_*, ...). They are not OpenTTD settings, so writing them
    # would pollute the generated cfg -- which is preserved as the provenance
    # record of the world played -- with keys OpenTTD silently ignores.
    for key, value in (settings or {}).items():
        if key.startswith("_"):
            continue
        cfg_content = _patch_ini_value(cfg_content, key, value)

    # Company slots AFTER settings so agent_companies aren't overridden
    # by the scenario's num_ai_companies (which excludes agent slots).
    total_companies = ai_opponents + agent_companies
    if total_companies > 0:
        cfg_content = _patch_ini_value(cfg_content, "ai_in_multiplayer", "true")
        cfg_content = _patch_ini_value(cfg_content, "difficulty.max_no_competitors", str(total_companies))
        cfg_content = _patch_ini_value(cfg_content, "difficulty.competitors_interval", "0")

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

    # --- Disable OpenTTD autosave when nttd save is off ---
    effective = settings or {}
    if int(effective.get("_save_interval_seconds", "0")) <= 0:
        cfg_content = dst_cfg.read_text()
        cfg_content = _patch_ini_value_in_section(
            cfg_content, "gui", "autosave_interval", "0",
        )
        cfg_content = _patch_ini_value_in_section(
            cfg_content, "gui", "autosave_on_exit", "false",
        )
        cfg_content = _patch_ini_value_in_section(
            cfg_content, "gui", "autosave_on_network_disconnect", "false",
        )
        dst_cfg.write_text(cfg_content)

    # --- Create session-specific directories (only as needed) ---
    (session_dir / "scenario").mkdir(exist_ok=True)
    if int(effective.get("_save_interval_seconds", "0")) > 0:
        (session_dir / "save").mkdir(exist_ok=True)
    if int(effective.get("_screenshot_interval_seconds", "0")) > 0:
        (session_dir / "screenshot").mkdir(exist_ok=True)

    logger.info(
        "Built session config: %s (game_port=%d, admin_port=%d)",
        session_dir,
        game_port,
        admin_port,
    )
    return session_dir
