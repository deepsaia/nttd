"""Benchmark tests -- stub.

Full benchmark tests require a running OpenTTD server and will be written
after the end-to-end 4-agent test run validates the full pipeline.

Run with: uv run pytest tests/test_benchmark.py -v
"""
import pytest


def test_benchmark_placeholder() -> None:
    """Placeholder -- real benchmark tests require a running OpenTTD server."""
    pytest.skip("Benchmark tests not yet implemented -- requires OpenTTD server")
