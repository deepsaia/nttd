"""Port allocation across concurrent sessions.

An evolution-strategies run starts a population of episodes at once, so session
starts overlap. They collided: a session is only added to ``self.runtimes`` after
its OpenTTD process has spawned, which takes about eight seconds, and
``start_session`` awaits several times in between -- so every concurrent caller read
an empty registry and took the same pair.

Verified against a live server before the fix: four concurrent starts were all
handed game_port 4000. After it: 4000, 4002, 4004, 4006, in 8.6s rather than the
33s a serial loop takes.

Run with: uv run pytest tests/test_port_allocation.py -v
"""

from __future__ import annotations

from pathlib import Path

from nttd.runtime.session_manager import SessionManager


def _manager(tmp_path: Path) -> SessionManager:
    return SessionManager(
        openttd_binary="/nonexistent",
        base_config_dir=tmp_path,
        sessions_dir=tmp_path,
    )


def test_successive_allocations_do_not_repeat(tmp_path: Path) -> None:
    """The regression. Nothing is registered between these calls, which is exactly
    the state two concurrent starts are in."""
    manager = _manager(tmp_path)
    pairs = [manager._allocate_ports() for _ in range(4)]

    game_ports = [pair[0] for pair in pairs]
    assert len(set(game_ports)) == 4, f"ports collided: {game_ports}"


def test_game_ports_are_even_and_admin_ports_follow(tmp_path: Path) -> None:
    """The admin port is derived as game+1, so an odd game port would overlap the
    previous session's admin port."""
    manager = _manager(tmp_path)
    for _ in range(3):
        game_port, admin_port = manager._allocate_ports()
        assert game_port % 2 == 0
        assert admin_port == game_port + 1


def test_a_released_pair_is_reused(tmp_path: Path) -> None:
    """Otherwise a long-lived server running an ES population would walk up the
    range and eventually exhaust it."""
    manager = _manager(tmp_path)
    first = manager._allocate_ports()
    manager._allocate_ports()
    manager._release_ports(*first)

    assert manager._allocate_ports() == first


def test_releasing_an_unreserved_pair_is_harmless(tmp_path: Path) -> None:
    """Teardown runs on paths where allocation may never have happened."""
    manager = _manager(tmp_path)
    manager._release_ports(9998, 9999)


def test_a_registered_runtime_still_blocks_its_ports(tmp_path: Path) -> None:
    """The reservation set is additional to the registry, not a replacement: a
    recovered session has a runtime but no reservation."""
    manager = _manager(tmp_path)
    game_port, admin_port = manager._allocate_ports()
    manager._release_ports(game_port, admin_port)

    class _Runtime:
        pass

    runtime = _Runtime()
    runtime.game_port = game_port  # type: ignore[attr-defined]
    runtime.admin_port = admin_port  # type: ignore[attr-defined]
    manager.runtimes["recovered"] = runtime  # type: ignore[assignment]

    assert manager._allocate_ports()[0] != game_port
