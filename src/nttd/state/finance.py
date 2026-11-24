"""Accumulate observed revenue using the game's completed economy quarters."""

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass
class RevenueLedger:
    """Revenue since the first financial observation, excluding its opening balance.

    A missing quarter is unknown, not the last sampled partial quarter. A later
    observation can fill a gap while it remains in OpenTTD's history window.
    """

    start_quarter: int | None = None
    opening_income: int = 0
    completed: dict[int, int] = field(default_factory=dict)

    def observe(self, quarter: int, income: int, history: Sequence[int | None]) -> int | None:
        if self.start_quarter is None:
            self.start_quarter = quarter
            self.opening_income = income
        if quarter < self.start_quarter:
            return None
        for offset, value in enumerate(history, 1):
            if value is not None:
                self.completed[quarter - offset] = int(value)
        if any(q not in self.completed for q in range(self.start_quarter, quarter)):
            return None
        return sum(self.completed[q] for q in range(self.start_quarter, quarter)) + income - self.opening_income
