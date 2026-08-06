"""A one-shot ADMIN_POLL request, which pyopenttdadmin does not provide.

The library models subscriptions but not polls, and some update types accept only one
of the two. ``CMD_NAMES`` is POLL-only: subscribing to it at any frequency makes OpenTTD
close the admin connection outright, which presents as "Connection lost" at session
start with nothing pointing at the cause.

Wire format, from the admin protocol:

    uint8   update type
    uint32  id relevant to the type (unused for CMD_NAMES, sent as 0)
"""

from __future__ import annotations

from pyopenttdadmin.enums import AdminUpdateType, PacketType

# Sent where the protocol wants an id and the update type has none.
_NO_ID = 0


class AdminPollPacket:
    """Ask the server once for a piece of information."""

    packet_type = PacketType.ADMIN_POLL

    def __init__(self, update_type: AdminUpdateType, extra: int = _NO_ID) -> None:
        self.update_type = update_type
        self.extra = extra

    def __repr__(self) -> str:
        return f"AdminPollPacket({self.update_type.name}, {self.extra})"

    def to_bytes(self) -> bytes:
        return bytes([self.update_type.value]) + self.extra.to_bytes(4, "little")
