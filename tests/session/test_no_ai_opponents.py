"""nttd runs no AI opponents, and will not start a session that would.

A benchmark run measures building a transport business in an empty market. A real
competitor from OpenTTD's content service would make it measure something else, and
something that varies: two runs on one seed would face different pressure depending on
which AI was installed and how it happened to play, with nothing on a result row
recording either. Runs that were never the same problem would sit in one table.

nttd is self-hosted, so this is not a defence against a contestant. It is what makes a
seed mean the same world to everybody.

The one AI shipped, ``nttd Idle``, holds a company slot open and sleeps. It exists
because OpenTTD has no other way to create a company that nobody is playing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nttd.constants import IDLE_AI_NAME
from nttd.runtime.config_builder import _assert_only_the_idle_ai
from tests.conftest import REPO_ROOT

_ROOT = REPO_ROOT
_BASE_CFG = _ROOT / "ottd_config" / "openttd.cfg"
_AI_DIR = _ROOT / "ottd_config" / "ai"


class TestWhatIsShipped:
    def test_the_idle_ai_is_the_only_one(self) -> None:
        """`library` is OpenTTD's own directory for AI libraries and is empty."""
        installed = sorted(
            p.name for p in _AI_DIR.iterdir() if p.is_dir() and p.name != "library"
        )
        assert installed == ["nttd-idle"]

    def test_the_idle_ai_does_nothing(self) -> None:
        """Not merely passive: it sleeps for the maximum interval, forever. An AI that
        merely had no strategy would still build, bid and rate towns."""
        source = (_AI_DIR / "nttd-idle" / "main.nut").read_text()
        assert "while (true)" in source
        assert "Sleep(2147483647)" in source
        for building in ("BuildRoad", "BuildRail", "BuildStation", "BuyVehicle"):
            assert building not in source

    def test_every_slot_in_the_shipped_config_is_the_idle_ai(self) -> None:
        """15 slots, which is the ceiling: 14 competitors plus the contestant. A slot
        left unnamed would let OpenTTD pick whatever AI it found."""
        content = _BASE_CFG.read_text()
        assert content.count(f'"{IDLE_AI_NAME}"') == 15
        _assert_only_the_idle_ai(content, _BASE_CFG)


class TestTheGuard:
    def _config(self, *names: str) -> str:
        entries = "\n".join(f'"{name}" = ' for name in names)
        return f"[difficulty]\nmax_no_competitors = 2\n\n[ai_players]\n{entries}\n"

    def test_the_idle_ai_passes(self) -> None:
        _assert_only_the_idle_ai(self._config(IDLE_AI_NAME, IDLE_AI_NAME), Path("x.cfg"))

    @pytest.mark.parametrize("intruder", ["AdmiralAI", "trAIns", "SimpleAI"])
    def test_a_real_ai_is_refused(self, intruder: str) -> None:
        with pytest.raises(ValueError, match="no AI opponents"):
            _assert_only_the_idle_ai(self._config(IDLE_AI_NAME, intruder), Path("x.cfg"))

    def test_the_refusal_names_the_offender(self) -> None:
        """So the fix is obvious from the message rather than requiring a config diff."""
        with pytest.raises(ValueError, match="AdmiralAI"):
            _assert_only_the_idle_ai(self._config("AdmiralAI"), Path("x.cfg"))

    def test_a_config_with_no_ai_section_is_fine(self) -> None:
        """No section means no AI players, which is the same guarantee."""
        _assert_only_the_idle_ai("[difficulty]\nmax_no_competitors = 0\n", Path("x.cfg"))

    def test_the_section_after_it_is_not_read_as_ai_players(self) -> None:
        """`[game_scripts]` follows `[ai_players]` in the real config and names the
        nttd GameScript. Reading past the section boundary would refuse every session."""
        content = (
            f'[ai_players]\n"{IDLE_AI_NAME}" = \n\n'
            '[game_scripts]\n"nttd GameScript" = \n'
        )
        _assert_only_the_idle_ai(content, Path("x.cfg"))


class TestSessionStartRefuses:
    def test_building_a_config_dir_raises(self, tmp_path: Path) -> None:
        """The guard runs where the config is built, so a session with a tampered base
        config never spawns rather than running and looking ordinary."""
        from nttd.runtime.config_builder import build_session_config

        base = tmp_path / "base"
        base.mkdir()
        (base / "openttd.cfg").write_text(
            '[network]\nserver_port = 3979\n\n[ai_players]\n"AdmiralAI" = \n',
        )

        with pytest.raises(ValueError, match="no AI opponents"):
            build_session_config(
                session_dir=tmp_path / "session",
                base_config_dir=base,
                game_port=4000,
                admin_port=4001,
                admin_password="x",
            )
