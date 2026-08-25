"""One nttd server per sessions directory, and the run that paid for it.

A second `nttd server` was a kill switch for every live run on the first. uvicorn runs the
application's startup hooks BEFORE it binds its socket, so the second server adopted a live
session, connected to its OpenTTD, discovered the port was taken, and took the ordinary
shutdown path out, which stops every session it has adopted:

    12:09:39  Recovered session 20260825-113321ist-daring-pebble
    12:09:39  Connected to Unnamed Server (OpenTTD 15.3, map 256x256)
    ERROR:    [Errno 48] address already in use
    12:09:40  Final save captured: save/final.sav
    12:09:45  Session ... stopped (reason=nttd_shutdown)

That run ended at day 189 of 366, with 723 cargo delivered and $22.88 of reported spend against
it, because a second process failed to start.

Two layers, and the order matters. The CLI checks the port before it spawns anything, which
turns the common case into one readable line. This lock is the guarantee behind it: acquired
before `recover_orphans` and released after `shutdown_all`, so the window in which a process
may adopt or stop a session is exactly the window in which it holds the lock.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from nttd.runtime.server_lock import LOCK_NAME, ServerLock

_REPO = Path(__file__).resolve().parents[2]


def test_the_first_server_takes_the_lock(tmp_path: Path) -> None:
    lock = ServerLock(tmp_path)
    lock.acquire()
    try:
        assert (tmp_path / LOCK_NAME).exists()
        assert lock.holder() == os.getpid()
    finally:
        lock.release()


def test_a_second_server_is_refused_before_it_can_recover_anything(tmp_path: Path) -> None:
    """The whole point. It must fail BEFORE it adopts a session, not after."""
    first = ServerLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="another nttd server"):
            ServerLock(tmp_path).acquire()
    finally:
        first.release()


def test_the_refusal_names_the_directory_and_says_what_to_do(tmp_path: Path) -> None:
    """An error a reader cannot act on sends them looking for a bug that is not there."""
    first = ServerLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(RuntimeError) as raised:
            ServerLock(tmp_path).acquire()
    finally:
        first.release()
    message = str(raised.value)
    assert str(tmp_path) in message
    assert str(os.getpid()) in message
    assert "NTTD_SESSIONS_DIR" in message


def test_a_failed_attempt_does_not_erase_the_holders_pid(tmp_path: Path) -> None:
    """Opened without truncating, so the loser cannot blank the winner's own record.

    Truncating on open would leave the holder's file empty, and the next refusal would say
    "pid unknown" about a process named in the file it had just cleared.
    """
    first = ServerLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(RuntimeError):
            ServerLock(tmp_path).acquire()
        assert first.holder() == os.getpid()
    finally:
        first.release()


def test_the_lock_is_free_again_once_released(tmp_path: Path) -> None:
    """Restarting a server must not need anything cleared by hand."""
    first = ServerLock(tmp_path)
    first.acquire()
    first.release()
    second = ServerLock(tmp_path)
    second.acquire()
    second.release()


def test_releasing_a_lock_that_was_never_held_is_not_an_error(tmp_path: Path) -> None:
    """The lifespan releases in a finally, which can run after a failed acquire."""
    ServerLock(tmp_path).release()


def test_a_dead_holder_leaves_no_lock_to_clear(tmp_path: Path) -> None:
    """flock rather than a pid file, and this is the reason.

    A pid file outlives the process that wrote it, so a crashed server leaves a lock nothing
    will clear, and the next start needs a human and a --force flag to document. The kernel
    drops an flock when the holder dies, however it dies.
    """
    child = subprocess.run(
        [
            sys.executable, "-c",
            "import sys; sys.path.insert(0, 'src');"
            "from nttd.runtime.server_lock import ServerLock;"
            f"ServerLock({str(tmp_path)!r}).acquire();"
            "import os; os._exit(1)",
        ],
        cwd=_REPO,
        capture_output=True,
    )
    assert child.returncode == 1, child.stderr.decode()

    survivor = ServerLock(tmp_path)
    survivor.acquire()
    survivor.release()


def test_two_directories_are_two_servers(tmp_path: Path) -> None:
    """The port is the wrong thing to protect.

    Two servers on DIFFERENT ports sharing one sessions directory would both recover the same
    OpenTTD processes and either could stop the other's runs, so the directory is what is
    exclusive. Two directories are genuinely independent and one server each is allowed.
    """
    one, other = tmp_path / "a", tmp_path / "b"
    first, second = ServerLock(one), ServerLock(other)
    first.acquire()
    second.acquire()
    try:
        assert first.holder() == second.holder() == os.getpid()
    finally:
        first.release()
        second.release()


def test_the_directory_is_created_if_it_does_not_exist(tmp_path: Path) -> None:
    """A first ever run has no sessions directory yet and must not fail on the lock."""
    fresh = tmp_path / "not" / "there" / "yet"
    lock = ServerLock(fresh)
    lock.acquire()
    lock.release()
    assert fresh.is_dir()


def test_the_lifespan_takes_the_lock_before_it_recovers_anything() -> None:
    """Read off the source, because the ORDER is the fix and nothing else asserts it.

    Recovery adopts live OpenTTD processes and `shutdown_all` stops them. Acquiring after
    either would reproduce the incident exactly: a process that adopts a session and then
    discovers it should not have started.
    """
    body = (_REPO / "src" / "nttd" / "api" / "app.py").read_text()
    acquire = body.index("lock.acquire()")
    assert acquire < body.index("recover_orphans"), "the lock must come before recovery"
    assert acquire < body.index("shutdown_all"), "and before anything can be stopped"
    assert body.index("shutdown_all") < body.index("lock.release()"), (
        "released only after shutdown_all, so the lock covers the whole dangerous window"
    )


# --- the CLI's own pre-flight, which is what a reader actually sees ---------------------------


def test_the_cli_checks_the_port_and_the_directory_before_spawning_anything() -> None:
    """Both checks, in the parent, so the failure is a line and not a stack trace.

    The lock inside the application is the authority, but it raises out of uvicorn's lifespan,
    and what reaches the terminal is a traceback through contextlib and asyncio with the useful
    sentence at the bottom of it. That is how the original incident read too: the message said
    "address already in use" and the reader went looking at the network.
    """
    body = (_REPO / "src" / "nttd" / "cli" / "server_command.py").read_text()
    port_check = body.index("_port_is_taken(host, port)")
    lock_check = body.index("probe_lock.acquire()")
    spawn = body.index("subprocess.run(cmd)")
    assert port_check < spawn, "the port is checked before a child exists"
    assert lock_check < spawn, "and so is the sessions directory"


def test_a_failing_server_is_reported_rather_than_traced() -> None:
    """`check=True` raises CalledProcessError, which typer renders as a stack trace through
    nttd's own frames, and the reader then goes looking for a bug in the CLI. The child has
    already said what went wrong; the parent only needs to not bury it."""
    body = (_REPO / "src" / "nttd" / "cli" / "server_command.py").read_text()
    # The call, not the word: the comment above it explains why check=True is wrong here, so
    # matching the bare string finds the explanation and calls it the defect.
    assert "subprocess.run(cmd, check=True)" not in body
    assert "finished.returncode" in body
