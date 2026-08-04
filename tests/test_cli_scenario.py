"""Tests for `nttd scenario` and the CLI's use of tier-prefixed routes.

Two things worth guarding. First, a scenario can be checked without spawning
OpenTTD: before this, the only way to learn a config had a typo was to start a run,
generate a world, and watch the first check fail -- a long way round for a T4
benchmark. Second, the CLI calls the canonical tier prefixes rather than the
deprecated unprefixed aliases, so it models the boundary it is crossing.

Run with: uv run pytest tests/test_cli_scenario.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nttd.cli.app import app

runner = CliRunner()
_REPO = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# scenario validate
# ---------------------------------------------------------------------------


def test_a_shipped_example_validates() -> None:
    result = runner.invoke(
        app, ["scenario", "validate", str(_REPO / "config/benchmark/t2_example.conf")],
    )
    assert result.exit_code == 0
    assert "Valid" in result.stdout


def test_validate_reports_every_problem_at_once(tmp_path: Path) -> None:
    """An author should be able to fix a config in one pass rather than discovering
    one violation per run."""
    config = tmp_path / "bad.conf"
    config.write_text(
        'scenario {\n  name = "bad"\n  scored = true\n  map {\n'
        '    size_x = 2048\n    landscape = "martian"\n'
        '    number_towns = "high"\n    starting_year = 1960\n  }\n}\n'
    )
    result = runner.invoke(app, ["scenario", "validate", str(config)])

    assert result.exit_code == 1
    for expected in ("size_x", "landscape", "number_towns", "starting_year"):
        assert expected in result.stdout, f"{expected} not reported"


def test_validate_exits_nonzero_on_a_bad_config(tmp_path: Path) -> None:
    """So it is usable as a pre-run gate in a script."""
    config = tmp_path / "bad.conf"
    config.write_text('scenario { scored = true, map { starting_year = 1960 } }')
    assert runner.invoke(app, ["scenario", "validate", str(config)]).exit_code == 1


def test_validate_reports_a_missing_file_clearly(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scenario", "validate", str(tmp_path / "absent.conf")])
    assert result.exit_code == 1
    assert "No such config" in result.stdout


def test_validate_warns_about_a_missing_seed(tmp_path: Path) -> None:
    """An unseeded world cannot be regenerated, so a result from it is uncheckable."""
    config = tmp_path / "unseeded.conf"
    config.write_text('scenario { name = "x", map { size_x = 256, size_y = 256 } }')
    result = runner.invoke(app, ["scenario", "validate", str(config)])

    assert result.exit_code == 0
    assert "seed" in result.stdout.lower()


def test_free_play_is_not_held_to_the_profile(tmp_path: Path) -> None:
    """Only a scored scenario is constrained; authoring and debugging are not."""
    config = tmp_path / "free.conf"
    config.write_text(
        'scenario {\n  name = "free"\n  map {\n    size_x = 256\n'
        '    number_towns = "high"\n    starting_year = 1960\n    seed = 7\n  }\n}\n'
    )
    result = runner.invoke(app, ["scenario", "validate", str(config)])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# scenario profile
# ---------------------------------------------------------------------------


def test_profile_shows_the_rules_in_force() -> None:
    result = runner.invoke(app, ["scenario", "profile"])
    assert result.exit_code == 0
    assert "starting_year" in result.stdout
    assert "terrain_type" in result.stdout


def test_profile_names_its_source() -> None:
    """A reader needs to know whether edits to profile.conf are taking effect, or
    whether it fell back to the built-in rules."""
    result = runner.invoke(app, ["scenario", "profile"])
    assert "profile.conf" in result.stdout or "built-in fallback" in result.stdout


def test_profile_states_whether_scoring_is_open() -> None:
    result = runner.invoke(app, ["scenario", "profile"])
    assert "conformance is the credential" in result.stdout.lower() or (
        "restricted to a fixed slate" in result.stdout.lower()
    )


# ---------------------------------------------------------------------------
# The CLI uses canonical tier prefixes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module",
    ["benchmark_command", "session_commands", "result_command", "analyze_command"],
)
def test_no_command_uses_a_deprecated_unprefixed_path(module: str) -> None:
    """The unprefixed forms still work, which is exactly why a drift here would go
    unnoticed: the CLI would keep functioning while no longer stating which trust
    tier it is crossing."""
    source = (_REPO / "src" / "nttd" / "cli" / f"{module}.py").read_text()
    for legacy in (
        'f"{url}/admin/', 'f"{base_url}/admin/',
        'f"{url}/sessions/', 'f"{base_url}/sessions/',
    ):
        assert legacy not in source, f"{module} calls a deprecated path: {legacy}"


def test_every_cli_route_exists_in_the_api() -> None:
    """Catches the failure gym_env had: six endpoints that had not existed for some
    time, with nothing to notice because no test ever called them."""
    import re

    from nttd.api.app import app as api

    known = set(api.openapi()["paths"])
    pattern = re.compile(r'f"\{(?:base_)?url\}(/v1/[^"]*)"')

    for path in (_REPO / "src" / "nttd" / "cli").glob("*.py"):
        for raw in pattern.findall(path.read_text()):
            # Normalise f-string interpolations to OpenAPI path params.
            route = raw.replace("{session_id}", "{session_id}")
            route = re.sub(r"\{[a-z_]+\}", lambda m: m.group(0), route)
            route = route.split("?")[0]
            assert route in known, f"{path.name} calls {route}, which the API does not serve"
