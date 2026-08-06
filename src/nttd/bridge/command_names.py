"""Parses OpenTTD's command id-to-name table, which pyopenttdadmin gets wrong.

Every logged command carries a numeric id and nothing else, so without this table an
action log reads ``cmd_57``. The server sends the table once, on request.

The library's ``CmdNamesPacket`` splits the payload on null bytes and returns whatever
strings fall out. The payload is not a list of strings: it is a repeated
``bool, uint16 id, string name``. Splitting it yields an interleaved mess of binary id
fragments and names::

    [0] 'z\\x01'                  <- packet type byte and a bool
    [2] 'CmdBuildRailroadTrack'
    [3] '\\x01\\x01'                <- the next id, read as if it were a name
    [4] 'CmdRemoveRailroadTrack'

Indexing that by command id returns an arbitrary string. It is also lossy: the library
decodes as UTF-8 and some id bytes are not valid UTF-8, so the whole packet is dropped
with "Unknown packet type 0x7a" rather than parsed.

So nttd parses it directly. Getting this wrong is quiet rather than loud: the log fills
with confident, wrong command names.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Repeated: one byte flag, two byte id, null-terminated name.
_FLAG_WIDTH = 1
_ID_WIDTH = 2
_TERMINATOR = b"\x00"


def parse_command_names(body: bytes) -> dict[int, str]:
    """Read a SERVER_CMD_NAMES payload into ``{command_id: name}``.

    Args:
        body: The packet body, starting at the packet type byte.

    Returns:
        The mapping, or as much of it as parsed cleanly. A malformed tail stops the
        walk rather than discarding the names already read.
    """
    names: dict[int, str] = {}
    offset = 1  # skip the packet type byte

    while offset + _FLAG_WIDTH + _ID_WIDTH <= len(body):
        if not body[offset]:
            break  # the terminating false flag
        offset += _FLAG_WIDTH

        command_id = int.from_bytes(body[offset:offset + _ID_WIDTH], "little")
        offset += _ID_WIDTH

        end = body.find(_TERMINATOR, offset)
        if end < 0:
            logger.warning("Command name table ended mid-name at offset %d", offset)
            break

        try:
            names[command_id] = body[offset:end].decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("Undecodable command name for id %d", command_id)
        offset = end + 1

    return names
