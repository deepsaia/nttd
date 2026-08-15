"""Delete everything one session wrote to disk.

Separate from the monitor that calls it, because the question "which files belong to this
session" is a storage question and ``session_paths`` is its single authority. Routing the
delete through ``session_dir`` means the id is validated by the same allowlist every other
reader uses, so a crafted id cannot reach outside the sessions root.

Deliberately not a partial cleanup. ``_cleanup_config_artifacts`` already exists for the
narrower job of removing OpenTTD's config files while preserving the recording; this is the
whole directory, including the Parquet traces and the final savegame, because the operator
asking for it is asking to reclaim the space and clear the list.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from nttd.store import session_paths

logger = logging.getLogger(__name__)


def remove_session(session_id: str, sessions_root: Path | None = None) -> bool:
    """Delete a session's directory. True if something was removed.

    Raises ``InvalidSessionIdError`` for an id that is not a session id, which is the same
    refusal every other path builder gives, rather than deleting something unexpected.

    ``sessions_root`` exists because the monitor can be pointed at a directory other than the
    configured one, and deleting from the default root while displaying another would remove
    the wrong session. The id is validated either way.
    """
    if sessions_root is None:
        directory = session_paths.session_dir(session_id)
    else:
        directory = Path(sessions_root) / session_paths.validate_session_id(session_id)
    if not directory.exists():
        logger.info("Session %s has nothing on disk to remove", session_id)
        return False
    if not directory.is_dir():
        logger.warning("Session %s path is not a directory, refusing to remove", session_id)
        return False
    shutil.rmtree(directory)
    logger.info("Removed session %s and everything under %s", session_id, directory)
    return True
