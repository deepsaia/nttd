"""A desyncing admin stream is visible, and recovers.

This is the one fault that corrupts results rather than stopping a run. When the stream goes
out of step, a reply lands against the wrong correlation id, every layer above reports
something plausible and wrong, and nothing says so: send_gamescript waited on an id whose
answer was already lost, timed out, and returned the same word a slow pathfinder returns.
Measured historically at 247,869 unparseable packets in one session.

The cause was fixed in #60, by chunking on size alone. These cover what happens if it
desyncs anyway.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from nttd.bridge.admin_client import (
    _UNPARSEABLE_RESYNC_AFTER,
    AdminClient,
)


def _client() -> AdminClient:
    client = AdminClient.__new__(AdminClient)
    client._connected = True
    client._intentional_disconnect = False
    client._reader = None
    client._writer = None
    client._gs_events = {}
    client._gs_responses = {}
    client._gs_totals = {}
    client._gs_counter = 0
    client.unparseable_total = 0
    client.unparseable_streak = 0
    client.resyncs = 0
    return client


def test_one_bad_packet_is_counted_and_tolerated() -> None:
    """A handful can follow a single oversized reply, so one is noise rather than a fault."""
    client = _client()
    resynced = asyncio.run(client._note_unparseable(ValueError("bad"), "{trunc"))

    assert resynced is False
    assert client.unparseable_total == 1
    assert client.unparseable_streak == 1
    assert client.resyncs == 0


def test_a_run_of_them_resynchronises() -> None:
    """A sustained run means the tail of something is still arriving as fragments, so every
    later reply is landing against the wrong id. Starting again beats interpreting them."""
    client = _client()
    reconnected: list[bool] = []

    async def _reconnect() -> None:
        reconnected.append(True)
        client._connected = True

    client._reconnect_loop = _reconnect

    async def _drive() -> bool:
        out = False
        for _ in range(_UNPARSEABLE_RESYNC_AFTER):
            out = await client._note_unparseable(ValueError("bad"), "{trunc")
        return out

    assert asyncio.run(_drive()) is True
    assert reconnected == [True]
    assert client.resyncs == 1
    # Reset, so the next run has to earn its own reconnect rather than tripping immediately.
    assert client.unparseable_streak == 0
    assert client.unparseable_total == _UNPARSEABLE_RESYNC_AFTER


def test_waiters_are_released_when_the_stream_restarts() -> None:
    """They are waiting on ids whose replies are already lost. A timeout each is slower and
    says less than a transport error now."""
    client = _client()
    client._reconnect_loop = _noop
    waiter = asyncio.Event()
    client._gs_events = {"gs_1": waiter}

    async def _drive() -> None:
        for _ in range(_UNPARSEABLE_RESYNC_AFTER):
            await client._note_unparseable(ValueError("bad"), "{trunc")

    asyncio.run(_drive())
    assert waiter.is_set()


def test_a_good_packet_clears_the_streak() -> None:
    """Otherwise scattered noise across a long session would eventually force a reconnect."""
    client = _client()
    asyncio.run(client._note_unparseable(ValueError("bad"), "{trunc"))
    assert client.unparseable_streak == 1

    client.unparseable_streak = 0  # what the poll loop does on a successful parse
    asyncio.run(client._note_unparseable(ValueError("bad"), "{trunc"))
    assert client.unparseable_streak == 1
    assert client.resyncs == 0


def test_the_counters_are_reported_not_only_logged() -> None:
    client = _client()
    client.unparseable_total = 7
    client.resyncs = 2
    health = client.transport_health()

    assert health["unparseable_total"] == 7
    assert health["resyncs"] == 2
    assert health["connected"] is True


@pytest.mark.parametrize(
    ("garbled", "expected_error"),
    [(0, "timeout"), (4, "transport")],
)
def test_a_lost_reply_is_distinguished_from_a_slow_one(
    garbled: int, expected_error: str,
) -> None:
    """Two different faults wore the same word. A slow command is the caller's problem and
    worth budgeting for; a lost reply is nttd's, and retrying against it makes things worse.
    """
    client = _client()
    sent: list[Any] = []

    async def _send(packet: Any) -> None:
        sent.append(packet)
        # Whatever the stream did while the command was outstanding.
        client.unparseable_total += garbled

    client._send = _send

    reply = asyncio.run(client.send_gamescript("get_date", timeout=0.01))

    assert reply["success"] is False
    assert reply["error"] == expected_error
    assert "reason" in reply
    assert json.loads(sent[0].json_str)["action"] == "get_date"


def test_a_timeout_does_not_strand_the_partial_reply() -> None:
    """The chunks that did arrive are dropped, and the dict they sat in does not grow.

    _merge_chunks is what normally pops _gs_responses, and it only runs on success, so a
    timeout used to leave the partial reply there for the life of the session. Measured at
    50 KB stranded for one timing-out get_map_terrain, and a policy that retries such a scan
    stranded that again every attempt.

    Note the fix cannot live in the `finally` beside the other two pops, which is the obvious
    place: `finally` runs before `return self._merge_chunks(...)`, so popping there would throw
    away the chunks of every successful reply. This asserts the success path still works, for
    exactly that reason.
    """
    client = _client()

    async def _send_partial(packet: Any) -> None:
        correlation_id = next(iter(client._gs_responses))
        client._gs_responses[correlation_id].append({"partial": "x" * 1000})

    client._send = _send_partial
    reply = asyncio.run(client.send_gamescript("get_map_terrain", timeout=0.01))

    assert reply["success"] is False
    assert client._gs_responses == {}, "the partial reply was left behind"
    assert client._gs_events == {}
    assert client._gs_totals == {}


def test_a_successful_reply_still_reaches_the_caller() -> None:
    """The guard on the fix above: popping in the wrong place would empty this."""
    client = _client()

    async def _send_and_answer(packet: Any) -> None:
        correlation_id = next(iter(client._gs_responses))
        client._gs_responses[correlation_id].append({"success": True, "result": [1, 2, 3]})
        client._gs_events[correlation_id].set()

    client._send = _send_and_answer
    reply = asyncio.run(client.send_gamescript("get_towns", timeout=1.0))

    assert reply["success"] is True
    assert reply["result"] == [1, 2, 3]
    assert client._gs_responses == {}


async def _noop() -> None:
    return None
