"""Shared pytest fixtures and configuration."""

import pytest


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
