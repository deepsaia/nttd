"""Recording what a person does in the game window.

nttd's action log used to record only submissions through its own API, and the API is
optional. Demonstrated before this landed: emptying actions.parquet, claiming zero
actions and refreshing the manifest digests earned a `verified` verdict, because
`action_log_consistent` compares the log against the result's own counts and a run that
recorded nothing satisfies it.

Three things had to be got right, and each was wrong first:

  * CMD_NAMES is POLL-only. Subscribing to it at any frequency makes OpenTTD close the
    admin connection, which presents as "Connection lost" at session start with nothing
    naming the cause.
  * The name table is `bool, uint16 id, string`, repeated, and arrives in several
    packets. pyopenttdadmin splits it on nulls, which yields binary fragments
    interleaved with names, and assigning rather than merging each packet kept 8 of 145.
  * CMD_LOGGING reports every command the game accepts, including the ones nttd's own
    GameScript issues. Counting those double-counted every API action.
"""

from __future__ import annotations

from typing import Any

import pytest

from nttd.bridge.command_names import parse_command_names


def _names_payload(entries: list[tuple[int, str]], terminate: bool = True) -> bytes:
    """Build a SERVER_CMD_NAMES body the way OpenTTD does."""
    body = bytearray([0x7A])  # packet type
    for command_id, name in entries:
        body += b"\x01"
        body += command_id.to_bytes(2, "little")
        body += name.encode() + b"\x00"
    if terminate:
        body += b"\x00"
    return bytes(body)


class TestCommandNames:
    def test_it_reads_ids_and_names_in_pairs(self) -> None:
        payload = _names_payload([(0, "CmdBuildRailroadTrack"), (1, "CmdRemoveRailroadTrack")])
        assert parse_command_names(payload) == {
            0: "CmdBuildRailroadTrack", 1: "CmdRemoveRailroadTrack",
        }

    def test_ids_are_not_positions(self) -> None:
        """The library treated the table as an ordered list, so a lookup by id
        returned whatever string happened to sit at that index."""
        payload = _names_payload([(57, "CmdSetCompanyMaxLoan"), (144, "CmdLast")])
        names = parse_command_names(payload)
        assert names[57] == "CmdSetCompanyMaxLoan"
        assert names[144] == "CmdLast"
        assert 0 not in names

    def test_a_truncated_table_keeps_what_it_read(self) -> None:
        """A malformed tail should not discard the names already parsed."""
        payload = _names_payload([(0, "CmdOne"), (1, "CmdTwo")], terminate=False)
        payload = payload[:-3]  # chop the last name's terminator and some bytes
        names = parse_command_names(payload)
        assert names[0] == "CmdOne"

    def test_an_empty_table_is_empty_not_an_error(self) -> None:
        assert parse_command_names(bytes([0x7A, 0x00])) == {}


class FakePacket:
    """A CmdLoggingPacket stand-in."""

    def __init__(self, client_id: int, company_id: int, cmd: int) -> None:
        self.client_id = client_id
        self.company_id = company_id
        self.cmd = cmd
        self.data = b""
        self.frame = 0


def _client(names: dict[int, str] | None = None) -> Any:
    from nttd.bridge.admin_client import AdminClient

    client = AdminClient(host="127.0.0.1", port=1)
    client._command_names = names or {}
    return client


class TestServerCommandsAreDropped:
    def test_a_command_from_the_server_is_not_recorded(self) -> None:
        """nttd's own GameScript issues commands. Recording them alongside the API
        action that caused them counted every submission twice."""
        client = _client()
        seen: list[dict[str, Any]] = []
        client.on_client_command(seen.append)

        from nttd.bridge.admin_client import CLIENT_ID_SERVER
        client._handle_client_command(FakePacket(CLIENT_ID_SERVER, 0, 5))

        assert seen == []

    def test_a_command_from_a_joined_client_is_recorded(self) -> None:
        """Joining clients are numbered from 2, so this is a person at a keyboard."""
        client = _client({5: "CmdBuildRoadStop"})
        seen: list[dict[str, Any]] = []
        client.on_client_command(seen.append)

        client._handle_client_command(FakePacket(2, 3, 5))

        assert len(seen) == 1
        assert seen[0]["command"] == "CmdBuildRoadStop"
        assert seen[0]["client_id"] == 2
        assert seen[0]["company_id"] == 3

    def test_an_unknown_id_falls_back_to_the_number(self) -> None:
        """Better a readable placeholder than a confident wrong name."""
        client = _client({})
        seen: list[dict[str, Any]] = []
        client.on_client_command(seen.append)

        client._handle_client_command(FakePacket(2, 0, 99))

        assert seen[0]["command"] == "cmd_99"


class TestRecording:
    def test_a_client_command_lands_in_the_action_log(self, tmp_path: Any) -> None:
        from nttd.store.recorder import SOURCE_CLIENT, SessionRecorder

        recorder = SessionRecorder("ses_probe", data_dir=str(tmp_path))
        recorder.record_client_command(
            {"command": "CmdBuildDock", "client_id": 2, "company_id": 0}, game_date=737800,
        )

        assert len(recorder._action_buffer) == 1
        row = recorder._action_buffer[0]
        assert row["source"] == SOURCE_CLIENT
        assert row["action_type"] == "CmdBuildDock"
        assert row["client_id"] == 2
        assert row["game_date"] == 737800

    def test_it_counts_toward_the_company_total(self, tmp_path: Any) -> None:
        """Otherwise a run played by hand still reports zero actions."""
        from nttd.store.recorder import SessionRecorder

        recorder = SessionRecorder("ses_probe", data_dir=str(tmp_path))
        recorder.record_client_command(
            {"command": "CmdBuildDock", "client_id": 2, "company_id": 0}, game_date=1,
        )
        assert recorder.action_counts()[0]["total_actions"] == 1


class TestSubscriptionFrequencies:
    """OpenTTD closes the connection on an unsupported frequency, and says nothing
    about why. Both of these are pinned because getting one wrong looks like a
    network fault."""

    def test_cmd_logging_is_automatic_only(self) -> None:
        from pyopenttdadmin.enums import AdminUpdateFrequency, AdminUpdateType
        from pyopenttdadmin.enums import AdminUpdateTypeFrequencyMatrix as matrix

        assert matrix[AdminUpdateType.CMD_LOGGING] == [AdminUpdateFrequency.AUTOMATIC]

    def test_cmd_names_is_poll_only(self) -> None:
        from pyopenttdadmin.enums import AdminUpdateFrequency, AdminUpdateType
        from pyopenttdadmin.enums import AdminUpdateTypeFrequencyMatrix as matrix

        assert matrix[AdminUpdateType.CMD_NAMES] == [AdminUpdateFrequency.POLL]

    def test_the_client_polls_for_names_and_subscribes_for_commands(self) -> None:
        import inspect

        from nttd.bridge.admin_client import AdminClient

        source = inspect.getsource(AdminClient.subscribe_defaults)
        assert "CMD_LOGGING, AdminUpdateFrequency.AUTOMATIC" in source
        assert "poll_command_names" in source
        assert "CMD_NAMES, AdminUpdateFrequency" not in source, (
            "subscribing to CMD_NAMES drops the admin connection"
        )


def test_the_poll_packet_matches_the_wire_format() -> None:
    """uint8 update type, uint32 id. The library models subscriptions but not polls."""
    from pyopenttdadmin.enums import AdminUpdateType

    from nttd.bridge.poll_packet import AdminPollPacket

    packet = AdminPollPacket(AdminUpdateType.CMD_NAMES)
    assert packet.to_bytes() == bytes([AdminUpdateType.CMD_NAMES.value, 0, 0, 0, 0])


@pytest.mark.parametrize("source", ["api", "client"])
def test_the_action_log_records_where_an_action_came_from(source: str) -> None:
    from nttd.store.recorder import _ACTIONS_SCHEMA

    assert "source" in _ACTIONS_SCHEMA.names
    assert "client_id" in _ACTIONS_SCHEMA.names
