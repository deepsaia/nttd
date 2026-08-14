"""Benchmark scoring.

The primary score is OpenTTD's own quarterly performance rating (0-1000). It is
game-authoritative, blends eight components including 40% annual cargo delivered,
and is hard to game -- unlike raw company value, which rises simply by drawing a
loan. Cargo delivered breaks ties; company value is recorded for display but does
not affect rank.

Scores carry a ``score_version``. Changing how a score is computed must bump it,
so a leaderboard can tell which entries are comparable instead of silently mixing
definitions.

**v2 is the first version that produces a score at all.** v1 read OpenTTD's rating for
quarter 0, the quarter in progress, which is never rated: it answered -1 for the life of
every run. Every result row nttd ever wrote scored 0 and carried rating_available=False,
across a dozen sessions and years of game time. v1 rows are not worth migrating because
none of them holds a score, so the board accepts v2 only.
"""

from __future__ import annotations

from dataclasses import dataclass

from nttd.schemas.company import Company

# OpenTTD answers -1 for a quarter it cannot rate. The GameScript now asks for quarter 1,
# the last completed one, so this is reached when a run ends before its first quarter
# closes rather than, as it used to be, always.
_RATING_UNAVAILABLE = -1

# Before the first quarter closes, quarter 1 answers 0 rather than -1, and a genuinely
# terrible company also rates 0. The two are indistinguishable from the rating alone, so
# a run shorter than a quarter cannot be scored honestly. Every benchmark scenario runs
# for years, so this bounds a mistake rather than a real entry.
_DAYS_IN_QUARTER = 92


@dataclass(frozen=True)
class CompanyScore:
    """One company's score. One definition, so there is no version to carry.

    ``performance_rating`` is stored RAW, exactly as the game answers it, including -1 for a
    quarter it could not rate. It used to be split into two columns, a clamped ``primary_score``
    and a ``rating_available`` flag, which is one fact recorded twice: the flag existed only to
    restore the information the clamp destroyed. -1 already sorts below 0, so the clamp was not
    even needed for ordering.

    ``total_cargo`` is the run's delivered cargo and is also what breaks a tie, so it is one
    column rather than a ``tiebreak_cargo`` beside an identical ``total_cargo``.
    """

    company_id: int
    company_name: str
    performance_rating: int
    total_cargo: int
    rail_cargo: int
    road_cargo: int
    water_cargo: int
    air_cargo: int
    company_value: int
    balance: int
    loan: int

    @property
    def rating_available(self) -> bool:
        """Derived, not stored: -1 is the game saying it could not rate the quarter."""
        return self.performance_rating != _RATING_UNAVAILABLE

    def sort_key(self) -> tuple[int, int]:
        """Descending rank order: the rating, then the cargo that broke the tie."""
        return (self.performance_rating, self.total_cargo)


def score_company(company: Company) -> CompanyScore:
    """Score one company from its final state, as the game reports it."""
    return CompanyScore(
        company_id=company.id,
        company_name=company.name or "",
        performance_rating=company.performance_rating,
        # The RUN's cargo, not the quarter in progress: q0_cargo resets at every quarter
        # boundary and a run ends on one, so the old tiebreak read 0 for every company that
        # ever played. One measured run carried 3,526 units and tied at nothing.
        total_cargo=company.cargo_delivered_total,
        rail_cargo=company.rail_cargo,
        road_cargo=company.road_cargo,
        water_cargo=company.water_cargo,
        air_cargo=company.air_cargo,
        company_value=company.value,
        balance=company.money,
        loan=company.loan,
    )


def rank_companies(
    companies: list[Company],
    contested_by: set[int] | None = None,
) -> list[CompanyScore]:
    """Score and rank the companies somebody actually played, best-first.

    Inactive companies are excluded: a bankrupt or removed company has no standing
    result.

    So are company slots nobody played. Every company in an nttd session is created by
    the ``nttd Idle`` AI, which sleeps forever so that a slot exists for a contestant to
    act through, and ``num_ai_companies`` adds more of the same rather than opponents.
    Without this filter a session configured for two "AI opponents" wrote three scored
    rows: the contestant, and two "Unnamed" companies at score 0 with no actions. A
    board ingesting that bundle would read three entries for one run.

    Args:
        contested_by: Company ids somebody played, meaning they hold a participant
            token or have a recorded action. None keeps every active company, which is
            what a caller without that knowledge should get rather than a silent
            filter. The action half matters for humans: somebody who joins a slot from
            the game window has no token, and dropping them would be worse than the
            phantom rows this removes.
    """
    scored = [
        company for company in companies
        if company.is_active and (contested_by is None or company.id in contested_by)
    ]
    scores = [score_company(company) for company in scored]
    scores.sort(key=CompanyScore.sort_key, reverse=True)
    return scores
