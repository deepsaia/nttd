"""Evaluates end conditions after each heartbeat step.

End conditions are configured via config/scenario.conf.
Logic "any" (default): simulation stops when the first enabled condition is met.
Logic "all": simulation stops when every enabled condition is simultaneously met.
"""
import logging
import time
from dataclasses import dataclass

from nttd.config.scenario_config import EndConditionsConfig
from nttd.schemas.snapshot import StateSnapshot

logger = logging.getLogger(__name__)


@dataclass
class EndResult:
    triggered: bool
    reason: str = ""


class EndConditionChecker:
    """Evaluates the configured end conditions against the current snapshot.

    Create once, call check() after each heartbeat beat.
    """

    def __init__(self, config: EndConditionsConfig, start_time: float | None = None) -> None:
        self._config = config
        self._start_time = start_time or time.time()
        self._heartbeat_count = 0
        # Running totals for cargo delivered (accumulated across snapshots)
        self._cargo_delivered: int = 0
        self._prev_income: dict[int, int] = {}

    def reset(self) -> None:
        self._start_time = time.time()
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
        ])

    def _evaluate_all(self, snapshot: StateSnapshot) -> list[EndResult]:
        cfg = self._config
        results: list[EndResult] = []

        # ---- Wall-clock time limit ----------------------------------------
        if cfg.time_limit.enabled:
            elapsed_minutes = (time.time() - self._start_time) / 60.0
            if elapsed_minutes >= cfg.time_limit.wall_minutes:
                results.append(EndResult(
                    triggered=True,
                    reason=f"Time limit reached ({cfg.time_limit.wall_minutes} min wall clock)",
                ))

        # ---- In-game calendar date ----------------------------------------
        if cfg.game_date_limit.enabled:
            # game_date is stored as days-since-epoch in OpenTTD; year ≈ date // 365 + 1
            current_year = snapshot.game.game_date // 365 + 1
            if current_year >= cfg.game_date_limit.end_year:
                results.append(EndResult(
                    triggered=True,
                    reason=f"Game year {current_year} reached end year {cfg.game_date_limit.end_year}",
                ))

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
