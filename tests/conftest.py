"""Shared fixtures, and the one path every test needs.

Tests live in subject directories under `tests/`, so a file two levels down was deriving the
repository root by counting parents. Moving a file then changed the count, and the failure was
`FileNotFoundError` on a path assembled from a wrong root: 26 files broke that way in one move,
which is a poor reason to break a test.

`REPO_ROOT` is found by walking up to the directory holding `pyproject.toml`, so it does not
care where the file asking is.
"""

from pathlib import Path

import pytest


def _find_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("no pyproject.toml above tests/, so the repository root is unknown")


REPO_ROOT = _find_root()


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repository root, for tests reading source or config files."""
    return REPO_ROOT


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip gs_test marked tests unless -m gs_test is explicitly passed."""
    if config.getoption("-m") and "gs_test" in config.getoption("-m"):
        return
    skip_gs = pytest.mark.skip(reason="gs_test requires -m gs_test (needs live OpenTTD)")
    for item in items:
        if "gs_test" in item.keywords:
            item.add_marker(skip_gs)


def pytest_addoption(parser):  # type: ignore[no-untyped-def]
    """Add CLI options for GS integration tests."""
    parser.addoption(
        "--session-id",
        action="store",
        default=None,
        help="Session ID for gs_test integration tests (requires running nttd + OpenTTD)",
    )
    parser.addoption(
        "--base-url",
        action="store",
        default="http://localhost:8000",
        help="Base URL of the nttd API server",
    )
    parser.addoption(
        "--company-id",
        action="store",
        type=int,
        default=0,
        help="Company ID for gs_test integration tests",
    )
    parser.addoption(
        "--keep-session",
        action="store_true",
        default=False,
        help="Keep the test session alive after tests (skip teardown)",
    )
