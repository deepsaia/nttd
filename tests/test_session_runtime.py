"""Tests for SessionRuntime process spawning.

Focus: the map seed must reach the OpenTTD command line as ``-G``. Experiment
(scripts/experiment_seed_determinism.py) established that setting
game_creation.generation_seed in the per-session cfg does NOT reproduce a map --
two servers sharing that value generated different worlds -- while ``-G`` did.
So a regression here would silently give every contestant a different world
while the run still claimed to be seeded, which is worse than no seed at all.

These tests stub out process creation and the admin connection, so no OpenTTD
process is spawned.

Run with: uv run pytest tests/test_session_runtime.py -v
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nttd.runtime.session_runtime import SessionRuntime


class _FakeProcess:
    """Stand-in for asyncio.subprocess.Process."""

    pid = 4242

    async def wait(self) -> int:
        return 0

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


@pytest.fixture
def runtime(tmp_path: Path) -> SessionRuntime:
    return SessionRuntime(
        session_id="ses_test",
        game_port=4000,
        admin_port=4001,
        config_dir=tmp_path,
    )


@pytest.fixture
def captured_argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture argv passed to create_subprocess_exec; skip the admin handshake."""
    calls: list[list[str]] = []

    async def fake_exec(*args: Any, **_kwargs: Any) -> _FakeProcess:
        calls.append(list(args))
        return _FakeProcess()

    async def fake_wait_for_admin_port(self: SessionRuntime, _password: str) -> bool:
        return False  # short-circuits start_server right after the spawn

    async def fake_shutdown(self: SessionRuntime) -> None:
        return None

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(SessionRuntime, "_wait_for_admin_port", fake_wait_for_admin_port)
    monkeypatch.setattr(SessionRuntime, "shutdown", fake_shutdown)
    return calls


async def test_seed_is_passed_as_G_flag(
    runtime: SessionRuntime, captured_argv: list[list[str]]
) -> None:
    """A map seed must appear as ``-G <seed>`` in argv."""
    await runtime.start_server("/fake/openttd", "pw", map_seed=1001)

    assert len(captured_argv) == 1
    argv = captured_argv[0]
    assert "-G" in argv, f"seed must be passed as -G; got {argv}"
    assert argv[argv.index("-G") + 1] == "1001"


async def test_no_seed_means_no_G_flag(
    runtime: SessionRuntime, captured_argv: list[list[str]]
) -> None:
    """Without a seed the map is explicitly random -- no -G at all."""
    await runtime.start_server("/fake/openttd", "pw")

    argv = captured_argv[0]
    assert "-G" not in argv


async def test_seed_zero_is_honoured(
    runtime: SessionRuntime, captured_argv: list[list[str]]
) -> None:
    """Seed 0 is a valid seed, not 'unset' -- guards against a falsy check."""
    await runtime.start_server("/fake/openttd", "pw", map_seed=0)

    argv = captured_argv[0]
    assert "-G" in argv
    assert argv[argv.index("-G") + 1] == "0"


async def test_dedicated_and_config_flags_still_present(
    runtime: SessionRuntime, captured_argv: list[list[str]], tmp_path: Path
) -> None:
    """The seed must not displace -D (dedicated) or -c (config path)."""
    await runtime.start_server("/fake/openttd", "pw", map_seed=7)

    argv = captured_argv[0]
    assert argv[0] == "/fake/openttd"
    assert "-D" in argv
    assert argv[argv.index("-c") + 1] == str(tmp_path / "openttd.cfg")


def test_map_seed_defaults_to_none(runtime: SessionRuntime) -> None:
    """map_seed is provenance state; unset until SessionManager assigns it."""
    assert runtime.map_seed is None
