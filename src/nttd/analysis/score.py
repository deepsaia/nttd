"""Benchmark scoring.

The primary score is OpenTTD's own quarterly performance rating (0-1000). It is
game-authoritative, blends eight components including 40% annual cargo delivered,
and is hard to game -- unlike raw company value, which rises simply by drawing a
loan. Cargo delivered breaks ties; company value is recorded for display but does
not affect rank.

Scores carry a ``score_version``. Changing how a score is computed must bump it,
so a leaderboard can tell which entries are comparable instead of silently mixing
definitions.
"""

from __future__ import annotations

from dataclasses import dataclass

from nttd.schemas.company import Company

# Bump on any change to how primary/tiebreak are derived.
SCORE_VERSION = "v1"

# OpenTTD reports -1 until it has a full quarter of history to rate.
_RATING_UNAVAILABLE = -1


@dataclass(frozen=True)
class CompanyScore:
    """A single company's score under a specific score version."""

    company_id: int
    company_name: str
    score_version: str
    primary: int
    tiebreak: int
    company_value: int
    balance: int
    loan: int
    rating_available: bool

    def sort_key(self) -> tuple[int, int]:
        """Descending rank order: primary, then tiebreak."""
        return (self.primary, self.tiebreak)


def score_company(company: Company) -> CompanyScore:
    """Score one company from its final state.

    An unavailable rating scores 0 rather than -1, so a company that never earned
    a rating ranks below one that did without inverting the ordering.
    """
    rating = company.performance_rating
    available = rating != _RATING_UNAVAILABLE
    return CompanyScore(
        company_id=company.id,
        company_name=company.name or "",
        score_version=SCORE_VERSION,
        primary=max(rating, 0),
        tiebreak=company.q0_cargo,
        company_value=company.value,
        balance=company.money,
        loan=company.loan,
        rating_available=available,
    )


def rank_companies(companies: list[Company]) -> list[CompanyScore]:
    """Score and rank companies best-first.

    Inactive companies are excluded: a bankrupt or removed company has no
    standing result.
    """
    scores = [score_company(c) for c in companies if c.is_active]
    scores.sort(key=CompanyScore.sort_key, reverse=True)
    return scores
