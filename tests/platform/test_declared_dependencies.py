"""Every third-party module nttd imports is declared, and every declared one is used.

Both halves were wrong, and the same edit exposed both.

seaborn and matplotlib were declared and imported by nothing at all: 49 MB installed for no
feature. Removing them broke `nttd analyze`, because analysis/plots.py imports pandas and
reports/video.py imports PIL, and neither was declared. They were arriving as dependencies of
seaborn and matplotlib respectively. So the unused entries were load-bearing by accident, and
deleting them revealed two imports that had never been declared at all.

An undeclared import is a working install by luck. It survives until the intermediate package
drops the dependency, and then it fails in a fresh environment while the developer's own
machine keeps working, which is the worst shape a packaging bug can take.
"""

from __future__ import annotations

import ast
import sys
import tomllib

from tests.conftest import REPO_ROOT

_ROOT = REPO_ROOT
_SRC = _ROOT / "src"

# Import name to distribution name, where they differ.
_DISTRIBUTION_OF = {
    "PIL": "pillow",
    "dateutil": "python-dateutil",
    "pkg_resources": "setuptools",
    "yaml": "pyyaml",
}

# av is imported directly by reports/video.py and is declared as the pyav extra of imageio
# rather than on its own line. That is a declaration: the extra exists to pull it in.
_DECLARED_BY_EXTRA = {"av"}

# Declared for a reason other than an import in src/. Kept short on purpose, because "it is
# needed somehow" is how an unused 49 MB dependency survives.
_NOT_IMPORTED_ON_PURPOSE = {
    "pytest",          # the suite, which lives in tests/ rather than src/
    "pytest-asyncio",  # a pytest plugin, loaded by pytest and never imported
    "ruff",            # a binary, not a library
    "uvicorn",         # run as a subprocess by nttd server
    "kaleido",         # plotly's image export engine, called through fig.write_image
    "setuptools",      # a build-time requirement of a dependency
    "websockets",      # uvicorn's websocket implementation, selected by name
}


def _declared() -> set[str]:
    """Everything pyproject declares, base and extras alike.

    An optional extra is still a declaration: `nttd publish` imports huggingface_hub, which
    is under the `publish` extra because most installs never file a bundle. What this test
    is for is an import nothing declares ANYWHERE, which is a working install by luck.
    """
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]
    requirements = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        requirements.extend(extra)
    names = set()
    for requirement in requirements:
        head = requirement.split("[")[0]
        for separator in (">=", "<=", "==", "~=", ">", "<", "!="):
            head = head.split(separator)[0]
        names.add(head.strip().lower())
    return names


def _imported() -> dict[str, set[str]]:
    """Top-level third-party module names imported anywhere in src/, and by which files."""
    found: dict[str, set[str]] = {}
    for path in _SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                if name == "nttd" or name in sys.stdlib_module_names:
                    continue
                found.setdefault(name, set()).add(str(path.relative_to(_ROOT)))
    return found


def test_every_imported_module_is_declared() -> None:
    """The half that broke a fresh install while the developer's machine kept working."""
    declared = _declared()
    undeclared = {
        name: sorted(users)
        for name, users in _imported().items()
        if name not in _DECLARED_BY_EXTRA
        and _DISTRIBUTION_OF.get(name, name).lower() not in declared
    }
    assert not undeclared, f"imported but not declared in pyproject: {undeclared}"


def test_every_declared_dependency_is_used() -> None:
    """The half that cost 49 MB for no feature.

    A new entry here needs either an import in src/ or a line in the exemption set saying
    what uses it, which is a smaller thing to write than an explanation later.
    """
    imported_distributions = {
        _DISTRIBUTION_OF.get(name, name).lower() for name in _imported()
    } | _DECLARED_BY_EXTRA
    unused = sorted(
        name for name in _declared()
        if name not in imported_distributions and name not in _NOT_IMPORTED_ON_PURPOSE
    )
    assert not unused, f"declared in pyproject and imported by nothing: {unused}"
