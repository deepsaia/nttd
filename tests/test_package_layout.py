"""Enforces project layout rules that are easy to erode.

Rule: no logic in any __init__.py. Package __init__ files mark a directory as a
package and nothing more, so import side effects stay predictable and a module's
home is always obvious from its path.

The CLI is the case that tempts a violation, because Typer must register every
command before main() runs. That registration lives in nttd/cli/app.py, and
pyproject points the console script at nttd.cli.app:main.

Run with: uv run pytest tests/test_package_layout.py -v
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SEARCH_ROOTS = ("src", "tests", "agents", "examples", "scripts")


def _init_files() -> list[Path]:
    found: list[Path] = []
    for root in _SEARCH_ROOTS:
        base = _REPO_ROOT / root
        if not base.is_dir():
            continue
        found.extend(
            path for path in base.rglob("__init__.py")
            if "__pycache__" not in path.parts and ".venv" not in path.parts
        )
    return sorted(found)


def test_init_files_exist_to_be_checked() -> None:
    """Guard against the check silently passing because it found nothing."""
    assert _init_files(), "expected to find __init__.py files to check"


def test_all_init_files_contain_no_logic() -> None:
    """Every __init__.py must be empty apart from comments."""
    offenders: dict[str, list[str]] = {}
    for path in _init_files():
        code = [
            line for line in path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if code:
            offenders[str(path.relative_to(_REPO_ROOT))] = code[:5]

    assert not offenders, (
        "__init__.py files must hold no logic; move it to a named module. "
        f"Offenders: {offenders}"
    )


def test_console_script_points_at_a_real_module() -> None:
    """The nttd entry point must not target a package __init__."""
    with open(_REPO_ROOT / "pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    target = pyproject["project"]["scripts"]["nttd"]
    module, _, func = target.partition(":")
    assert func == "main"
    assert module != "nttd.cli", "entry point must not live in a package __init__"

    module_path = _REPO_ROOT / "src" / Path(*module.split(".")).with_suffix(".py")
    assert module_path.is_file(), f"{target} does not resolve to {module_path}"


def test_cli_app_exposes_main_and_registers_commands() -> None:
    """The moved entry point must still build the full command tree."""
    from nttd.cli.app import app, main

    assert callable(main)
    registered = {command.name or command.callback.__name__ for command in app.registered_commands}
    for expected in ("server", "benchmark", "result", "analyze"):
        assert expected in registered, f"`nttd {expected}` is not registered"

    groups = {group.name for group in app.registered_groups}
    for expected in ("session", "agent", "mas"):
        assert expected in groups, f"`nttd {expected} ...` is not registered"
