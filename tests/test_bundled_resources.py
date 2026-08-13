"""nttd's data is found from the package, not by counting `..` to a repository root.

Five modules located the GameScript, the action manifest and the scenario files by walking up
from their own __file__ to the repository root. That works from a checkout and only from a
checkout. Measured on a wheel built before this: 179 files of code and no data, and an
installed nttd looked for its manifest at site-packages/../../config/actions/manifest.json,
because parents[3] from nttd/config/ climbs out of site-packages entirely.

The wheel contents themselves are checked by scripts/check_wheel_contents.py, which CI runs
against a built artifact. These cover the resolver.
"""

from __future__ import annotations

from pathlib import Path

from nttd import resources


def test_the_data_directory_exists_and_holds_the_gamescript() -> None:
    """From a checkout this is the repository root; from a wheel it is nttd/_data."""
    gamescript = resources.gamescript_dir() / "game" / "nttd-gs" / "main.nut"
    assert gamescript.exists(), gamescript


def test_the_base_openttd_config_is_findable() -> None:
    """Without it a session cannot be built: config_builder patches ports into a copy."""
    assert (resources.gamescript_dir() / "openttd.cfg").exists()


def test_the_generated_action_files_are_findable() -> None:
    for name in ("manifest.json", "enums.json", "descriptions.json"):
        assert resources.action_config(name).exists(), name


def test_the_shipped_scenarios_are_findable() -> None:
    for name in ("profile.conf", "t2_256_flat_1001_realtime.conf"):
        assert resources.scenario_config(name).exists(), name


def test_an_environment_override_wins(monkeypatch: object) -> None:
    """For an operator running against their own game files."""
    monkeypatch.setenv(resources.ENV_VAR, "/somewhere/else")  # type: ignore[attr-defined]
    assert resources.data_dir() == Path("/somewhere/else")
    assert resources.gamescript_dir() == Path("/somewhere/else/ottd_config")


def test_the_loaders_resolve_through_the_resolver() -> None:
    """The point of one authority: these used to compute their own paths and could disagree."""
    from nttd.config.action_manifest import MANIFEST_PATH
    from nttd.config.benchmark_profile import PROFILE_PATH
    from nttd.config.error_codes import ENUMS_PATH

    assert MANIFEST_PATH == resources.action_config("manifest.json")
    assert ENUMS_PATH == resources.action_config("enums.json")
    assert PROFILE_PATH == resources.scenario_config("profile.conf")


def test_the_version_comes_from_installed_metadata() -> None:
    """One source of truth, and it is the git tag the release created.

    pyproject used to carry a version as well, which is one fact in two places, and a release
    is when they diverge: pyproject said 0.1.0 while the 0.0.2 release was cut, so publish
    refused at its own gate and uploaded nothing.
    """
    from nttd.version import UNKNOWN, version

    reported = version()
    assert reported
    # Either a real version from metadata, or an honest unknown. Never a guess.
    assert reported == UNKNOWN or reported[0].isdigit(), reported


def test_pyproject_declares_the_version_dynamic() -> None:
    """A literal version here would be the duplication that broke the 0.0.2 release."""
    import tomllib

    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]

    assert "version" in project.get("dynamic", [])
    assert "version" not in project, "the version must come from the tag, not from pyproject"
