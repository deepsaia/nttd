"""What `nttd benchmark` tells a contestant has to be true of the run in front of them.

Three things it got wrong, each of which reads as the benchmark misbehaving rather than as a
display fault:

  * It counted its own polling cycles and labelled them "cycle". A stepped session correctly
    held at day one showed "cycle 3", which reads as three days elapsed.
  * It printed the realtime action route for every session. A stepped world never advances
    through that route, so a runner following the printed instructions would submit actions
    into a world frozen at day one.
  * It minted the session id from the config name, giving
    benchmark_benchmark-t1-256-flat-1001-stepped: the word twice, no date, and nothing that
    sorts by when the run happened.
"""

from __future__ import annotations

import inspect

from nttd.cli import benchmark_command


def test_the_config_name_is_not_the_session_id() -> None:
    """The id comes from the server, which mints the date-first shape everything else uses."""
    source = inspect.getsource(benchmark_command)
    assert '"name": f"benchmark_{cfg.name}"' not in source
    assert '"config_path": config' in source


def test_a_stepped_session_is_told_to_use_the_step_route() -> None:
    source = inspect.getsource(benchmark_command._print_attach_instructions)
    assert "/step" in source
    assert "stepped" in inspect.signature(benchmark_command._print_attach_instructions).parameters


def test_progress_is_counted_in_game_days_not_polls() -> None:
    source = inspect.getsource(benchmark_command._monitor_loop)
    assert "Game days played" in source
    # Code only: the docstring explains the fix and names the thing it removed.
    body = source.split('"""', 2)[2]
    assert "cycle" not in body.lower(), "a poll counter is not progress"


def test_the_day_budget_comes_from_the_scenario() -> None:
    from nttd.config.scenario_config import load

    cfg = load("config/benchmark/t1_256_flat_1001_stepped.conf")
    assert benchmark_command._day_budget(cfg) == 366


def test_a_game_date_is_shown_as_a_date() -> None:
    """737790 places nothing in time for a reader."""
    assert benchmark_command._readable(737790) == "01-Jan-2020"


def test_a_paused_session_says_it_is_waiting_rather_than_stalled() -> None:
    source = inspect.getsource(benchmark_command._monitor_loop)
    assert "Waiting for your runner" in source
