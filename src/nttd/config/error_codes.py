"""Names for the error numbers the GameScript reports.

The GameScript sends OpenTTD's error as two integers, a code and a category. Neither
means anything on its own, and both change between OpenTTD versions, so the names come
from ``config/actions/enums.json``, dumped from the build a session runs on, rather than
from a table written here.

Categories are rendered as bare words. ``ERR_CAT_TILE`` is noise in a table cell when the
column is already called category, and ``tile`` reads.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ENUMS_PATH = Path(__file__).resolve().parents[3] / "config" / "actions" / "enums.json"

_CATEGORY_PREFIX = "ERR_CAT_"


def _load() -> dict[str, dict[str, int]]:
    if not ENUMS_PATH.exists():
        logger.warning(
            "No enum dump at %s. Error codes will be reported as numbers: "
            "uv run python scripts/dump_gs_enums.py",
            ENUMS_PATH,
        )
        return {}
    try:
        return json.loads(ENUMS_PATH.read_text()).get("enums", {})
    except json.JSONDecodeError:
        logger.exception("Could not parse the enum dump at %s", ENUMS_PATH)
        return {}


_ERRORS = _load().get("GSError", {})

# Two names share a value in the dump: ERR_CAT_BIT_SIZE is a width marker rather than a
# category, and sorting puts it before ERR_CAT_RAIL, which is the real one. Excluded so a
# rail failure does not report its category as "bit_size".
_NOT_A_CATEGORY = {"ERR_CAT_BIT_SIZE"}

_CODE_TO_NAME: dict[int, str] = {
    value: name
    for name, value in sorted(_ERRORS.items())
    if not name.startswith(_CATEGORY_PREFIX)
}

_CATEGORY_TO_NAME: dict[int, str] = {
    value: name[len(_CATEGORY_PREFIX):].lower()
    for name, value in sorted(_ERRORS.items())
    if name.startswith(_CATEGORY_PREFIX) and name not in _NOT_A_CATEGORY
}


def error_name(code: int | None) -> str:
    """``ERR_NOT_ENOUGH_CASH`` for 257, or empty when the code is unknown."""
    if code is None:
        return ""
    return _CODE_TO_NAME.get(code, "")


def category_name(category: int | None) -> str:
    """``tile`` for 6, or empty when the category is unknown."""
    if category is None:
        return ""
    return _CATEGORY_TO_NAME.get(category, "")
