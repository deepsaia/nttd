"""Reassembling a GameScript reply that was split across packets.

The admin port carries about 1400 bytes per packet, so a large reply is chunked. It used
to be chunked only when the top level result was an array, which meant every handler
returning a table with the bulk nested inside it sent the whole thing in one packet.

get_map_terrain was the worst case: it returns {rows, from_y, to_y, truncated,
next_from_y, tiles_returned}, and one row of a 256 wide map is about 2000 characters, so
no band size was ever safe. The oversized packet desynced the stream, and from then on
replies were lost or handed to the wrong caller, which is what made action results
intermittently wrong. Measured at 247,869 unparseable packets in a single session, after
which every command timed out.

The reader now rebuilds a table from the chunks. The metadata matters as much as the
rows: a terrain band that lost `truncated` and `next_from_y` would look complete when it
was not.
"""

from __future__ import annotations

from typing import Any

from nttd.bridge.admin_client import AdminClient


def _merge(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the client's reassembly over a set of chunks, without a socket.

    The merge is the tail of send_gamescript. Exercising it directly keeps the test to
    the thing that was wrong, rather than standing up a game.
    """
    client = AdminClient.__new__(AdminClient)
    client._gs_responses = {"gs_1": list(chunks)}
    client._gs_totals = {"gs_1": len(chunks)}
    return AdminClient._merge_chunks(client, "gs_1")


def test_a_plain_array_reply_still_merges_as_a_list() -> None:
    """Every existing handler returns one of these, so it must not change shape."""
    merged = _merge([
        {"success": True, "result": [1, 2], "_chunk": 0, "_total": 2},
        {"success": True, "result": [3, 4], "_chunk": 1, "_total": 2},
    ])
    assert merged["result"] == [1, 2, 3, 4]


def test_chunks_are_ordered_by_their_index_not_by_arrival() -> None:
    """Packets can arrive out of order, and did once the stream was under load."""
    merged = _merge([
        {"success": True, "result": [3], "_chunk": 1, "_total": 3},
        {"success": True, "result": [5], "_chunk": 2, "_total": 3},
        {"success": True, "result": [1], "_chunk": 0, "_total": 3},
    ])
    assert merged["result"] == [1, 3, 5]


def test_a_table_reply_is_rebuilt_around_its_bulk_key() -> None:
    """get_map_terrain's shape: rows carried alongside scalars."""
    merged = _merge([
        {"success": True, "result": [{"y": 1}], "_chunk": 0, "_total": 2,
         "_key": "rows", "_meta": {"from_y": 1, "to_y": 2, "truncated": False}},
        {"success": True, "result": [{"y": 2}], "_chunk": 1, "_total": 2},
    ])
    assert merged["result"]["rows"] == [{"y": 1}, {"y": 2}]
    assert merged["result"]["from_y"] == 1


def test_the_metadata_survives_the_split() -> None:
    """A band that lost truncated and next_from_y would look complete when it was not.

    This is the whole reason the reassembly cannot simply concatenate arrays.
    """
    merged = _merge([
        {"success": True, "result": [{"y": 1}], "_chunk": 0, "_total": 2,
         "_key": "rows",
         "_meta": {"truncated": True, "next_from_y": 79, "tiles_returned": 20066}},
        {"success": True, "result": [{"y": 2}], "_chunk": 1, "_total": 2},
    ])
    assert merged["result"]["truncated"] is True
    assert merged["result"]["next_from_y"] == 79
    assert merged["result"]["tiles_returned"] == 20066


def test_a_table_reply_that_needed_only_one_chunk_is_not_mangled() -> None:
    """One chunk is returned as it came, so the key and meta are never applied twice."""
    merged = _merge([
        {"success": True, "result": [{"y": 1}], "_chunk": 0, "_total": 1,
         "_key": "rows", "_meta": {"truncated": False}},
    ])
    assert merged["result"] == [{"y": 1}]


def test_a_failed_reply_keeps_its_failure() -> None:
    merged = _merge([
        {"success": False, "result": [], "_chunk": 0, "_total": 2},
        {"success": False, "result": [], "_chunk": 1, "_total": 2},
    ])
    assert merged["success"] is False


def test_no_chunks_at_all_is_reported_rather_than_returning_nothing() -> None:
    """A dropped reply must not look like an empty answer."""
    client = AdminClient.__new__(AdminClient)
    client._gs_responses = {"gs_1": []}
    client._gs_totals = {"gs_1": 1}
    merged = AdminClient._merge_chunks(client, "gs_1")
    assert merged["success"] is False
    assert merged["error"] == "empty"
