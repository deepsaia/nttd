"""Ask the game whether built road or rail joins two tiles."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def line_exists(
    client: Any, from_x: int, from_y: int, to_x: int, to_y: int, transport_type: str,
) -> bool | None:
    """Whether a vehicle could travel it now, asked of the game rather than of the cache.

    None rather than False when the question cannot be put: a ship travels over open water
    so a track walk does not describe it, and a game that is not connected has no answer.
    False would read as "there is no line", which is a claim this has not earned.
    """
    if transport_type not in ("rail", "road"):
        return None
    if not client.connected:
        return None
    try:
        reply = await client.send_gamescript(
            "trace_route",
            {
                "from_x": from_x, "from_y": from_y, "to_x": to_x, "to_y": to_y,
                "transport_type": transport_type,
            },
            timeout=20.0,
        )
    except Exception:
        logger.debug("Could not trace the existing line", exc_info=True)
        return None
    if not reply.get("success"):
        return None
    return bool((reply.get("result") or {}).get("line_exists"))
