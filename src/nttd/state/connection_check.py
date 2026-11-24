"""Cached evidence and retry timing for one automatic connectivity probe."""

from dataclasses import dataclass


@dataclass
class ConnectionCheck:
    answer: bool | None
    checked_at: int
    next_check_at: int
    failures: int = 0
