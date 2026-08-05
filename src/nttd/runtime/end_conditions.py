"""Evaluates end conditions after each heartbeat step.

End conditions are configured in a scenario's end_conditions block.
Logic "any" (default): simulation stops when the first enabled condition is met.
Logic "all": simulation stops when every enabled condition is simultaneously met.
"""
import logging
import time
from dataclasses import dataclass

from nttd.config.scenario_config import EndConditionsConfig
from nttd.schemas.snapshot import StateSnapshot
from nttd.utils.game_date import game_date_to_year

logger = logging.getLogger(__name__)


@dataclass
class EndResult:
    triggered: bool
    reason: str = ""


class EndConditionChecker:
    """Evaluates the configured end conditions against the current snapshot.

    Create once, call check() after each heartbeat beat.

    The scored clock does not start at construction. Provisioning a session --
    generating the map, capturing tiles, registering agents -- takes a variable
    amount of wall time, so counting it would give two contestants on the same
    scenario materially different amounts of playing time. The clock starts on
    the first call to ``start_clock()``, which the runtime makes when the first
    action is submitted. Until then the wall-clock limit cannot expire.
    """

    def __init__(self, config: EndConditionsConfig, start_time: float | None = None) -> None:
        self._config = config
        # None means "not yet started" rather than "started at construction".
        self._start_time: float | None = start_time
        self._start_game_date: int | None = None
        self._heartbeat_count = 0
        # Running totals for cargo delivered (accumulated across snapshots)
        self._cargo_delivered: int = 0
        self._prev_income: dict[int, int] = {}

    def start_clock(self, game_date: int | None = None) -> bool:
        """Start the scored clock. Returns True if this call started it.

        Idempotent: later calls are ignored, so every action handler can call it
        without needing to know whether the run has already begun.
        """
        if self._start_time is not None:
            return False
        self._start_time = time.time()
        self._start_game_date = game_date
        logger.info("Scored clock started (game_date=%s)", game_date)
        return True

    @property
    def clock_started(self) -> bool:
        return self._start_time is not None

    @property
    def start_time(self) -> float | None:
        return self._start_time

    @property
    def start_game_date(self) -> int | None:
        return self._start_game_date

    def reset(self) -> None:
        self._start_time = None
        self._start_game_date = None
        self._heartbeat_count = 0
        self._cargo_delivered = 0
        self._prev_income = {}

    def check(self, snapshot: StateSnapshot) -> EndResult:
        """Return EndResult(triggered=True, reason=...) if any/all conditions are met."""
        self._heartbeat_count += 1
        results = self._evaluate_all(snapshot)
        triggered = [r for r in results if r.triggered]

        if not triggered:
            return EndResult(triggered=False)

        cfg = self._config
        if cfg.logic == "all":
            enabled_count = self._count_enabled()
            if len(triggered) >= enabled_count:
                reasons = "; ".join(r.reason for r in triggered)
                logger.info("All end conditions met: %s", reasons)
                return EndResult(triggered=True, reason=reasons)
            return EndResult(triggered=False)

        # logic == "any" (default)
        first = triggered[0]
        logger.info("End condition met: %s", first.reason)
        return EndResult(triggered=True, reason=first.reason)

    def _count_enabled(self) -> int:
        cfg = self._config
        return sum([
            cfg.time_limit.enabled,
            cfg.game_date_limit.enabled,
            cfg.revenue_threshold.enabled,
            cfg.cargo_threshold.enabled,
            cfg.max_heartbeats.enabled,
            cfg.bankruptcy.enabled,
        ])

    def _evaluate_all(self, snapshot: StateSnapshot) -> list[EndResult]:
        cfg = self._config
        results: list[EndResult] = []

        # ---- Wall-clock time limit ----------------------------------------
        # Only counts once the clock has started, so provisioning time is never
        # charged to the contestant.
        if cfg.time_limit.enabled and self._start_time is not None:
            elapsed_minutes = (time.time() - self._start_time) / 60.0
            if elapsed_minutes >= cfg.time_limit.wall_minutes:
                results.append(EndResult(
                    triggered=True,
                    reason=f"Time limit reached ({cfg.time_limit.wall_minutes} min wall clock)",
                ))

        # ---- In-game calendar date ----------------------------------------
        if cfg.game_date_limit.enabled:
            # game_date is days since year 0. The naive date // 365 + 1 ignores
            # leap days and is wrong by 2-3 years at OpenTTD's usual start dates.
            current_year = game_date_to_year(snapshot.game.game_date)
            if current_year >= cfg.game_date_limit.end_year:
                results.append(EndResult(
                    triggered=True,
                    reason=f"Game year {current_year} reached end year {cfg.game_date_limit.end_year}",
                ))

        # ---- Bankruptcy / company removal ---------------------------------
        # A contestant whose company is gone has no path back, so the run ends
        # rather than burning the remaining wall clock on a dead company.
        if cfg.bankruptcy.enabled:
            for company in snapshot.companies:
                if not company.is_active:
                    results.append(EndResult(
                        triggered=True,
                        reason=(
                            f"Company {company.id} ({company.name}) is no longer active "
                            f"(bankrupt or removed)"
                        ),
                    ))
                    break

        # ---- Revenue threshold (any single company) ----------------------
        if cfg.revenue_threshold.enabled:
            for company in snapshot.companies:
                if company.income >= cfg.revenue_threshold.total_revenue:
                    results.append(EndResult(
                        triggered=True,
                        reason=(
                            f"Company {company.id} ({company.name}) reached "
                            f"revenue {company.income:,} >= {cfg.revenue_threshold.total_revenue:,}"
                        ),
                    ))
                    break

        # ---- Cargo threshold (cumulative income proxy) -------------------
        # We approximate cargo delivered via the change in income since last heartbeat.
        if cfg.cargo_threshold.enabled:
            for company in snapshot.companies:
                prev = self._prev_income.get(company.id, company.income)
                delta = max(0, company.income - prev)
                self._cargo_delivered += delta
                self._prev_income[company.id] = company.income
            if self._cargo_delivered >= cfg.cargo_threshold.total_cargo_delivered:
                results.append(EndResult(
                    triggered=True,
                    reason=(
                        f"Cumulative cargo/revenue delivered "
                        f"{self._cargo_delivered:,} >= {cfg.cargo_threshold.total_cargo_delivered:,}"
                    ),
                ))

        # ---- Heartbeat count --------------------------------------------
        if cfg.max_heartbeats.enabled:
            if self._heartbeat_count >= cfg.max_heartbeats.count:
                results.append(EndResult(
                    triggered=True,
                    reason=f"Max heartbeats reached ({cfg.max_heartbeats.count})",
                ))

        return results
