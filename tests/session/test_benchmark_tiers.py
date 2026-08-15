"""Every shipped tier closes its quarters, from any start year.

The score is the rating of the last COMPLETED quarter. A run that ends just short of a
boundary therefore publishes a score describing the company as it stood a quarter earlier, and
the last quarter of building is the one that changed most.

That property was reasoned about in prose per config and could drift the moment a count was
hand-edited or the profile's start year moved. It is checked here instead, for the eight shipped
scenarios, across twelve start years so a leap year cannot break it: 2020 is a leap year, which
is why T2 is 366 days rather than 365, since day 365 would land on 2020-12-31, still inside Q4.

Two invariants, and they are not the same one. NEVER SHORT has to hold for any start year, leap
or not. MINIMAL only holds for the year profile.conf locks, because from a non-leap start the
same count lands two days past the boundary rather than one.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from nttd.config.scenario_config import load
from tests.conftest import REPO_ROOT

_BENCHMARKS = REPO_ROOT / "config" / "benchmark"

# The span each tier means, in game days, and the quarters that span closes.
_TIERS = {"t1": (366, 4), "t2": (731, 8), "t3": (1827, 20), "t4": (3653, 40)}

# The economy clock is fixed: no speed multiplier exists in OpenTTD 15.3.
_SECONDS_PER_GAME_DAY = 1.97


def _quarters_completed(start: date, days: int) -> int:
    """How many calendar quarters close strictly before the run's last day."""
    end = start + timedelta(days=days)
    done, year = 0, start.year
    while True:
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            closes = date(year, month, day)
            if closes < start:
                continue
            if closes < end:
                done += 1
            else:
                return done
        year += 1


def _configs(mode: str) -> list[Path]:
    return sorted(_BENCHMARKS.glob(f"t?_*_{mode}.conf"))


def test_all_four_tiers_ship_in_both_modes() -> None:
    """Eight examples: a contestant should not have to write one to start."""
    stepped = {p.name.split("_")[0] for p in _configs("stepped")}
    realtime = {p.name.split("_")[0] for p in _configs("realtime")}
    assert stepped == {"t1", "t2", "t3", "t4"}
    assert realtime == {"t1", "t2", "t3", "t4"}


@pytest.mark.parametrize("config", _configs("stepped"), ids=lambda p: p.name)
def test_a_stepped_tier_advances_one_day_at_a_time(config: Path) -> None:
    """One game day per step. A batch of any size still advances exactly one, because a step
    flushes its actions while the game is paused."""
    cfg = load(config)
    assert cfg.heartbeat.interval_days == 1
    assert cfg.runtime.mode == "stepped"


@pytest.mark.parametrize("config", _configs("stepped"), ids=lambda p: p.name)
def test_a_stepped_tier_is_bounded_in_steps_not_wall_time(config: Path) -> None:
    """The clock only advances when the contestant asks, so wall time would measure their
    hardware rather than how much of the game was played."""
    cfg = load(config)
    assert cfg.end_conditions.max_heartbeats.enabled
    assert not cfg.end_conditions.time_limit.enabled


@pytest.mark.parametrize("config", _configs("stepped"), ids=lambda p: p.name)
def test_a_stepped_tier_runs_its_tier_span(config: Path) -> None:
    cfg = load(config)
    days, _ = _TIERS[config.name.split("_")[0]]
    assert cfg.end_conditions.max_heartbeats.count == days


@pytest.mark.parametrize("config", _configs("stepped"), ids=lambda p: p.name)
@pytest.mark.parametrize("start_year", range(2019, 2031))
def test_a_stepped_tier_never_ends_short_of_its_quarters(
    config: Path, start_year: int,
) -> None:
    """The property that matters, and it has to hold for ANY start year.

    A run that ends short of the boundary publishes a score describing the company as it stood
    a quarter earlier. So every count must close at least its tier's quarters, whatever year the
    scenario starts in and whether or not that year is a leap year.

    Not "exactly one day past", which was the first thing tried here and is false: from a
    non-leap start, 182 days lands on 2 July, two days past the Q2 boundary. The invariant is
    never-short, not landing on an exact day.
    """
    days, quarters = _TIERS[config.name.split("_")[0]]
    closed = _quarters_completed(date(start_year, 1, 1), days)
    assert closed >= quarters, f"{days} days closes only {closed} quarters from {start_year}"


@pytest.mark.parametrize("config", _configs("stepped"), ids=lambda p: p.name)
def test_a_stepped_tier_is_the_shortest_span_that_closes_its_quarters(config: Path) -> None:
    """From the start year the profile locks, the count is minimal.

    Never-short is the safety property; this is the efficiency one. A count longer than needed
    spends a contestant's run on game time that changes no published figure, so from
    2020-01-01, which profile.conf locks, one day fewer must close one quarter fewer.
    """
    days, quarters = _TIERS[config.name.split("_")[0]]
    locked_start = date(2020, 1, 1)

    assert _quarters_completed(locked_start, days) == quarters
    assert _quarters_completed(locked_start, days - 1) == quarters - 1


@pytest.mark.parametrize("config", _configs("realtime"), ids=lambda p: p.name)
def test_a_realtime_tier_covers_the_same_span_as_its_twin(config: Path) -> None:
    """A tier is a span of game time, so both modes must cover the same one. Real time is
    bounded by the wall clock that produces that span, since the economy clock is fixed."""
    cfg = load(config)
    days, _ = _TIERS[config.name.split("_")[0]]
    expected = days * _SECONDS_PER_GAME_DAY / 60

    assert cfg.runtime.mode == "async_realtime"
    assert cfg.end_conditions.time_limit.enabled
    # Within a minute: the wall figure is rounded for legibility.
    assert abs(cfg.end_conditions.time_limit.wall_minutes - expected) < 1.0


@pytest.mark.parametrize(
    "config", _configs("stepped") + _configs("realtime"), ids=lambda p: p.name,
)
def test_a_tier_ends_when_a_scored_company_goes_bankrupt(config: Path) -> None:
    """Nothing left to measure, and a run that continues past it wastes the remaining span."""
    assert load(config).end_conditions.bankruptcy.enabled


@pytest.mark.parametrize(
    "config", _configs("stepped") + _configs("realtime"), ids=lambda p: p.name,
)
def test_a_tier_runs_no_ai_opponents(config: Path) -> None:
    """A benchmark measures building a business in an empty market. See constants.py."""
    cfg = load(config)
    assert cfg._raw is not None
    companies = cfg._raw.get("companies", {})
    assert int(companies.get("num_ai_companies", 0)) == 0
