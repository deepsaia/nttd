"""The savegame a verifier reloads to recompute a score.

It is the single most load-bearing artifact in a submission: without it a score is
self-reported. It used to be captured by a fire-and-forget task inside the real-time
loop, so a stepped run produced none at all, a manual stop produced none, and nothing
checked that any of them had been written.

The confirmation needs both halves, which a live probe established: OpenTTD's rcon
replies "Map successfully saved" *before* the bytes are flushed. Polling 40ms after a
confirmed save found the file present at 0 bytes, settling at 25 KB shortly after.

The second half is ``openttd -q``. The first implementation waited for the file size to
stop changing, and the growing-file test below caught it accepting a 100-byte partial
save, because the write paused between chunks for longer than the poll interval. Size
stability is a heuristic; ``-q`` is an integrity check.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nttd.runtime.final_save import FINAL_SAVE_NAME, FinalSaveCapture

SUCCESS_REPLY = ["Saving map...", "Map successfully saved to 'final.sav'."]


class FakeClient:
    """An AdminClient stand-in that writes the save the way OpenTTD would."""

    def __init__(
        self,
        save_dir: Path,
        reply: list[str] | None = None,
        connected: bool = True,
        content: bytes = b"x" * 2048,
        write: bool = True,
    ) -> None:
        self.connected = connected
        self.commands: list[str] = []
        self._save_dir = save_dir
        self._reply = SUCCESS_REPLY if reply is None else reply
        self._content = content
        self._write = write

    async def send_rcon(self, command: str) -> list[str]:
        self.commands.append(command)
        if self._write:
            self._save_dir.mkdir(parents=True, exist_ok=True)
            name = command.split(" ", 1)[1]
            (self._save_dir / f"{name}.sav").write_bytes(self._content)
        return self._reply


@pytest.fixture
def save_dir(tmp_path: Path) -> Path:
    return tmp_path / "save"


class TestTheHappyPath:
    @pytest.mark.asyncio
    async def test_a_confirmed_save_returns_its_path(self, save_dir: Path) -> None:
        client = FakeClient(save_dir)
        path = await FinalSaveCapture(client, save_dir, timeout=2.0).capture()

        assert path is not None
        assert path.name == f"{FINAL_SAVE_NAME}.sav"
        assert path.stat().st_size == 2048

    @pytest.mark.asyncio
    async def test_it_asks_openttd_to_save_under_a_known_name(
        self, save_dir: Path,
    ) -> None:
        """A verifier should not have to guess which file to reload."""
        client = FakeClient(save_dir)
        await FinalSaveCapture(client, save_dir, timeout=2.0).capture()

        assert client.commands == [f"save {FINAL_SAVE_NAME}"]


class TestTheFailuresThatUsedToBeSilent:
    @pytest.mark.asyncio
    async def test_an_unconfirmed_reply_is_not_a_save(self, save_dir: Path) -> None:
        """The reply is checked for the success line, not merely for returning."""
        client = FakeClient(save_dir, reply=["Cannot save: disk full"])
        assert await FinalSaveCapture(client, save_dir, timeout=0.5).capture() is None

    @pytest.mark.asyncio
    async def test_a_timed_out_rcon_is_not_a_save(self, save_dir: Path) -> None:
        """A timed-out rcon returns an empty list, and an empty list is not a save."""
        client = FakeClient(save_dir, reply=[])
        assert await FinalSaveCapture(client, save_dir, timeout=0.5).capture() is None

    @pytest.mark.asyncio
    async def test_a_file_that_never_appears_is_not_a_save(
        self, save_dir: Path,
    ) -> None:
        """OpenTTD claiming success does not by itself put bytes on disk."""
        client = FakeClient(save_dir, write=False)
        assert await FinalSaveCapture(client, save_dir, timeout=0.5).capture() is None

    @pytest.mark.asyncio
    async def test_an_empty_file_is_not_a_save(self, save_dir: Path) -> None:
        """The measured trap: the file exists at 0 bytes before the flush lands."""
        client = FakeClient(save_dir, content=b"")
        assert await FinalSaveCapture(client, save_dir, timeout=0.5).capture() is None

    @pytest.mark.asyncio
    async def test_no_admin_connection_means_no_rcon_attempt(
        self, save_dir: Path,
    ) -> None:
        client = FakeClient(save_dir, connected=False)
        assert await FinalSaveCapture(client, save_dir, timeout=0.5).capture() is None
        assert client.commands == []

    @pytest.mark.asyncio
    async def test_an_rcon_that_raises_does_not_stop_the_session(
        self, save_dir: Path,
    ) -> None:
        """A failed save must not prevent shutdown: a weaker submission beats a
        stuck process."""
        class Exploding(FakeClient):
            async def send_rcon(self, command: str) -> list[str]:
                raise RuntimeError("admin connection dropped")

        capture = FinalSaveCapture(Exploding(save_dir), save_dir, timeout=0.5)
        assert await capture.capture() is None


class TestIntegrity:
    """A save is complete when OpenTTD can read it, not when it stops growing."""

    @pytest.mark.asyncio
    async def test_a_partially_written_save_is_not_accepted(
        self, save_dir: Path, tmp_path: Path,
    ) -> None:
        """The case that caught the size heuristic.

        The file is written in two chunks with a pause longer than the poll interval,
        so the first chunk looks settled. Only an integrity check rejects it.
        """
        save_dir.mkdir(parents=True)
        target = save_dir / f"{FINAL_SAVE_NAME}.sav"

        class Growing(FakeClient):
            async def send_rcon(self, command: str) -> list[str]:
                target.write_bytes(b"a" * 100)
                asyncio.get_running_loop().call_later(
                    0.6, target.write_bytes, b"a" * 5000,
                )
                return SUCCESS_REPLY

        inspector = _inspector_accepting(tmp_path, minimum=5000)
        capture = FinalSaveCapture(
            Growing(save_dir), save_dir, openttd_binary=inspector, timeout=4.0,
        )
        path = await capture.capture()

        assert path is not None
        assert path.stat().st_size == 5000, "accepted a partially written save"

    @pytest.mark.asyncio
    async def test_a_save_openttd_cannot_read_is_not_a_save(
        self, save_dir: Path, tmp_path: Path,
    ) -> None:
        rejector = tmp_path / "reject"
        rejector.write_text("#!/bin/sh\nexit 1\n")
        rejector.chmod(0o755)

        capture = FinalSaveCapture(
            FakeClient(save_dir), save_dir, openttd_binary=str(rejector), timeout=0.8,
        )
        assert await capture.capture() is None

    @pytest.mark.asyncio
    async def test_a_missing_binary_degrades_rather_than_failing(
        self, save_dir: Path,
    ) -> None:
        """A broken install should not turn a good save into no save."""
        capture = FinalSaveCapture(
            FakeClient(save_dir), save_dir, openttd_binary=None, timeout=2.0,
        )
        assert await capture.capture() is not None


def _inspector_accepting(tmp_path: Path, minimum: int) -> str:
    """A stand-in for ``openttd -q``: exits 0 only once the file is big enough."""
    script = tmp_path / "inspect"
    script.write_text(
        "#!/bin/sh\n"
        f'size=$(wc -c < "$2"); [ "$size" -ge {minimum} ]\n'
    )
    script.chmod(0o755)
    return str(script)
