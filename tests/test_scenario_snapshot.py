"""Tests for the scenario provenance snapshot.

Every session copies the scenario it ran into its own directory, and the result
record digests that copy. The point is a run that stays verifiable after the source
files are edited or moved, so the snapshot has to stand alone.

It did not. Benchmark scenarios share the locked world settings through a HOCON
``include``, and a byte copy preserved the include LINE but not the included file.
Reparsing the snapshot then failed the include, and ``load`` treats a parse failure
as "use defaults" -- so the provenance record for a run generated at 2020 reported
1960. Silent, and wrong in the direction that matters.

Run with: uv run pytest tests/test_scenario_snapshot.py -v
"""

from __future__ import annotations

from pathlib import Path

from nttd.config.scenario_config import load, scenario_to_settings
from nttd.runtime.config_builder import _snapshot_scenario

_BENCHMARK_DIR = Path(__file__).parent.parent / "config" / "benchmark"


def test_a_snapshot_of_an_including_scenario_stands_alone(tmp_path: Path) -> None:
    """The regression this function exists for."""
    destination = tmp_path / "nttd_scenario.conf"
    _snapshot_scenario(_BENCHMARK_DIR / "t2_example.conf", destination)

    assert "include" not in destination.read_text(), (
        "an include in the snapshot points outside the session directory"
    )


def test_a_snapshot_yields_the_same_settings_as_the_source(tmp_path: Path) -> None:
    """Faithfulness is the whole value: a snapshot that parses to something else
    is worse than no snapshot, because it looks authoritative."""
    destination = tmp_path / "nttd_scenario.conf"
    _snapshot_scenario(_BENCHMARK_DIR / "t3_subarctic_example.conf", destination)

    source_settings = scenario_to_settings(load(_BENCHMARK_DIR / "t3_subarctic_example.conf"), strict=True)
    snapshot_settings = scenario_to_settings(load(destination), strict=True)
    assert snapshot_settings == source_settings


def test_the_locked_settings_survive_into_the_snapshot(tmp_path: Path) -> None:
    """Named explicitly, because these are the values that silently reverted."""
    destination = tmp_path / "nttd_scenario.conf"
    _snapshot_scenario(_BENCHMARK_DIR / "t2_example.conf", destination)

    settings = scenario_to_settings(load(destination), strict=True)
    assert settings["game_creation.starting_year"] == "2020"
    assert settings["difficulty.number_towns"] == "2"
    assert settings["game_creation.town_name"] == "0"


def test_a_scenario_without_includes_still_round_trips(tmp_path: Path) -> None:
    source = tmp_path / "plain.conf"
    source.write_text(
        'scenario {\n  name = "plain"\n  map {\n    size_x = 128\n'
        '    size_y = 128\n    seed = 77\n  }\n}\n'
    )
    destination = tmp_path / "nttd_scenario.conf"
    _snapshot_scenario(source, destination)

    settings = scenario_to_settings(load(destination), strict=True)
    assert settings["game_creation.map_x"] == "7"
    assert settings["_map_seed"] == "77"


def test_an_unparseable_scenario_is_copied_verbatim(tmp_path: Path) -> None:
    """An unfaithful snapshot beats none: the caller already validated what it runs,
    and losing the record entirely would leave the run unverifiable."""
    source = tmp_path / "broken.conf"
    source.write_text("scenario { this is not = = valid hocon {{{\n")
    destination = tmp_path / "nttd_scenario.conf"
    _snapshot_scenario(source, destination)

    assert destination.exists()
    assert destination.read_text() == source.read_text()


def test_a_missing_scenario_writes_nothing(tmp_path: Path) -> None:
    destination = tmp_path / "nttd_scenario.conf"
    _snapshot_scenario(tmp_path / "absent.conf", destination)
    assert not destination.exists()


def test_a_directory_is_not_snapshotted(tmp_path: Path) -> None:
    """scenario_path arriving as a directory should warn, not raise."""
    destination = tmp_path / "nttd_scenario.conf"
    _snapshot_scenario(_BENCHMARK_DIR, destination)
    assert not destination.exists()
