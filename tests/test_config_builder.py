"""Tests for config_builder INI patching logic.

Verifies that section-qualified keys (e.g. game_creation.map_x) are
correctly patched inside their INI sections, not appended to end of file.
"""

import textwrap

import pytest

from nttd.runtime.config_builder import _patch_ini_value, _patch_ini_value_in_section

SAMPLE_CFG = textwrap.dedent("""\
    [network]
    server_port = 3979
    server_admin_port = 3977

    [difficulty]
    max_no_competitors = 0
    competitors_interval = 10
    number_towns = 2
    max_loan = 300000

    [game_creation]
    starting_year = 1950
    map_x = 8
    map_y = 8
    landscape = 0
""")


class TestPatchIniValue:
    """Test the top-level _patch_ini_value dispatcher."""

    def test_simple_key_replaces_existing(self) -> None:
        result = _patch_ini_value(SAMPLE_CFG, "server_port", "4000")
        assert "server_port = 4000" in result
        assert "server_port = 3979" not in result

    def test_dotted_key_patches_correct_section(self) -> None:
        result = _patch_ini_value(SAMPLE_CFG, "game_creation.map_x", "7")
        lines = result.split("\n")
        # Find [game_creation] and check map_x is patched inside it
        in_gc = False
        found = False
        for line in lines:
            if line.strip() == "[game_creation]":
                in_gc = True
                continue
            if in_gc and line.strip().startswith("["):
                break
            if in_gc and "map_x" in line:
                assert "map_x = 7" in line
                found = True
        assert found, "map_x = 7 not found inside [game_creation]"

    def test_dotted_key_does_not_append_to_end(self) -> None:
        result = _patch_ini_value(SAMPLE_CFG, "game_creation.starting_year", "1960")
        # Should NOT have a bare "game_creation.starting_year" line
        assert "game_creation.starting_year" not in result

    def test_dotted_key_replaces_value(self) -> None:
        result = _patch_ini_value(SAMPLE_CFG, "game_creation.starting_year", "1960")
        assert "starting_year = 1960" in result
        assert "starting_year = 1950" not in result

    def test_difficulty_section_patched(self) -> None:
        result = _patch_ini_value(SAMPLE_CFG, "difficulty.max_no_competitors", "3")
        assert "max_no_competitors = 3" in result
        assert "max_no_competitors = 0" not in result

    def test_simple_key_appended_if_missing(self) -> None:
        result = _patch_ini_value(SAMPLE_CFG, "new_key", "new_value")
        assert "new_key = new_value" in result

    def test_underscore_prefix_treated_as_simple(self) -> None:
        """Keys starting with _ (like _ec_wall_minutes) are not section-qualified."""
        result = _patch_ini_value(SAMPLE_CFG, "_ec_wall_minutes", "10")
        assert "_ec_wall_minutes = 10" in result


class TestPatchIniValueInSection:
    """Test section-aware patching directly."""

    def test_existing_key_replaced(self) -> None:
        result = _patch_ini_value_in_section(SAMPLE_CFG, "game_creation", "map_x", "7")
        assert "map_x = 7" in result
        assert "map_x = 8" not in result

    def test_missing_key_inserted_in_section(self) -> None:
        result = _patch_ini_value_in_section(SAMPLE_CFG, "difficulty", "new_setting", "42")
        lines = result.split("\n")
        in_diff = False
        found = False
        for line in lines:
            if line.strip() == "[difficulty]":
                in_diff = True
                continue
            if in_diff and line.strip().startswith("["):
                # new_setting should appear before the next section
                break
            if in_diff and "new_setting = 42" in line:
                found = True
        assert found, "new_setting = 42 not found inside [difficulty]"

    def test_missing_section_created(self) -> None:
        result = _patch_ini_value_in_section(SAMPLE_CFG, "new_section", "foo", "bar")
        assert "[new_section]" in result
        assert "foo = bar" in result

    def test_last_section_key_appended(self) -> None:
        """Key added to the last section (no next section header to insert before)."""
        result = _patch_ini_value_in_section(SAMPLE_CFG, "game_creation", "snow_line_height", "10")
        assert "snow_line_height = 10" in result


class TestCompanySlotOrdering:
    """Verify that company slots applied AFTER settings don't get overridden."""

    def test_settings_then_company_slots(self) -> None:
        """Simulate the config_builder flow: settings loop then company setup."""
        cfg = SAMPLE_CFG

        # Step 1: Settings from scenario (includes max_no_competitors = 0)
        settings = {
            "game_creation.map_x": "7",
            "game_creation.map_y": "7",
            "game_creation.starting_year": "1960",
            "difficulty.max_no_competitors": "0",
            "difficulty.number_towns": "4",
        }
        for key, value in settings.items():
            cfg = _patch_ini_value(cfg, key, value)

        # Step 2: Company slot override (1 agent company)
        cfg = _patch_ini_value(cfg, "difficulty.max_no_competitors", "1")

        # The final value should be 1 (agent slot), not 0 (from settings)
        lines = cfg.split("\n")
        in_diff = False
        for line in lines:
            if line.strip() == "[difficulty]":
                in_diff = True
                continue
            if in_diff and line.strip().startswith("["):
                break
            if in_diff and "max_no_competitors" in line:
                assert "max_no_competitors = 1" in line
                return
        pytest.fail("max_no_competitors not found in [difficulty]")

    def test_all_settings_in_correct_sections(self) -> None:
        """Full scenario settings should land in correct INI sections."""
        cfg = SAMPLE_CFG
        settings = {
            "game_creation.map_x": "7",
            "game_creation.map_y": "7",
            "game_creation.starting_year": "1960",
            "game_creation.landscape": "0",
            "difficulty.max_no_competitors": "0",
            "difficulty.number_towns": "4",
            "difficulty.max_loan": "500000",
        }
        for key, value in settings.items():
            cfg = _patch_ini_value(cfg, key, value)

        # Verify each setting is in the right section
        assert "map_x = 7" in cfg
        assert "map_y = 7" in cfg
        assert "starting_year = 1960" in cfg
        assert "number_towns = 4" in cfg
        assert "max_loan = 500000" in cfg

        # No dotted keys should appear as-is
        assert "game_creation.map_x" not in cfg
        assert "difficulty.number_towns" not in cfg
