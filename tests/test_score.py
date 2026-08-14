"""Tests for benchmark scoring.

The score is the benchmark's identity, so these tests pin the decision that
performance_rating ranks and company_value does not. The repo's own published
data showed the old company_value sort inverting the true ranking
(docs/blog_nttd_multi_agent.md:141,144), which is exactly what this guards.

Run with: uv run pytest tests/test_score.py -v
"""

from __future__ import annotations

from nttd.analysis.score import SCORE_VERSION, rank_companies, score_company
from nttd.schemas.company import Company


def _company(cid: int, **kwargs: object) -> Company:
    return Company(id=cid, **kwargs)  # type: ignore[arg-type]


def test_primary_is_performance_rating() -> None:
    score = score_company(
        _company(0, performance_rating=740, cargo_delivered_total=1200, value=50_000),
    )
    assert score.primary == 740
    assert score.tiebreak == 1200
    assert score.score_version == SCORE_VERSION


def test_the_tiebreak_is_the_run_total_and_not_the_quarter_in_progress() -> None:
    """q0_cargo resets at every quarter boundary and a run ENDS on one, so it read 0 for
    every company that ever played. One measured run carried 3,526 units and tied at nothing.
    """
    company = _company(0, performance_rating=600, q0_cargo=0, cargo_delivered_total=3526)
    assert score_company(company).tiebreak == 3526


def test_a_company_that_delivered_nothing_still_ties_at_zero() -> None:
    assert score_company(_company(0, performance_rating=600)).tiebreak == 0


def test_company_value_does_not_affect_rank() -> None:
    """The core anti-regression: a loan-inflated value must not outrank skill.

    Drawing a loan raises company value without delivering anything, so a weaker
    agent could previously finish first.
    """
    weak_but_rich = _company(0, performance_rating=310, value=900_000, loan=500_000)
    strong_but_poor = _company(1, performance_rating=780, value=120_000)

    ranked = rank_companies([weak_but_rich, strong_but_poor])
    assert [s.company_id for s in ranked] == [1, 0]


def test_cargo_breaks_ties() -> None:
    a = _company(0, performance_rating=600, cargo_delivered_total=500)
    b = _company(1, performance_rating=600, cargo_delivered_total=900)
    assert [s.company_id for s in rank_companies([a, b])] == [1, 0]


def test_unavailable_rating_scores_zero_not_negative() -> None:
    """OpenTTD reports -1 before it has a quarter of history.

    Clamping to 0 keeps an unrated company below a rated one without letting a
    negative value invert the comparison.
    """
    unrated = score_company(_company(0))  # performance_rating defaults to -1
    assert unrated.primary == 0
    assert unrated.rating_available is False

    rated = score_company(_company(1, performance_rating=5))
    assert rated.rating_available is True
    assert rated.primary > unrated.primary


def test_inactive_companies_are_excluded() -> None:
    """A bankrupt or removed company has no standing result."""
    active = _company(0, performance_rating=400)
    gone = _company(1, performance_rating=900, is_active=False)
    ranked = rank_companies([active, gone])
    assert [s.company_id for s in ranked] == [0]


def test_ranking_is_stable_and_complete() -> None:
    companies = [
        _company(0, performance_rating=500, q0_cargo=10),
        _company(1, performance_rating=900, q0_cargo=20),
        _company(2, performance_rating=700, q0_cargo=30),
    ]
    ranked = rank_companies(companies)
    assert [s.company_id for s in ranked] == [1, 2, 0]
    assert len(ranked) == 3


def test_empty_input_gives_empty_ranking() -> None:
    assert rank_companies([]) == []


class TestTheRatingComesFromACompletedQuarter:
    """The bug that made every run score zero, pinned so it cannot return.

    `main.nut` read `GSCompany.GetQuarterlyPerformanceRating(cid, 0)`. Quarter 0 is the
    quarter in progress, and OpenTTD does not rate one until it ends, so it answered -1
    for the life of every run. Every snapshot nttd had written recorded -1 and every
    result row scored 0, across a dozen sessions and years of game time.

    Measured live at 1960-04-01, one quarter into a run: quarter 0 gave -1, quarter 1
    gave 30. After the fix a fresh session reported 30 where it had always reported -1.

    A source-level check, because the real one needs a running game past a quarter
    boundary. tests/test_gs_integration.py is where that belongs.
    """

    def _snapshot_block(self) -> str:
        from pathlib import Path

        source = Path(__file__).parent.parent / "ottd_config" / "game" / "nttd-gs" / "main.nut"
        text = source.read_text()
        start = text.index("performance_rating = GSCompany.GetQuarterlyPerformanceRating")
        return text[start:start + 120]

    def test_the_rating_does_not_ask_for_the_current_quarter(self) -> None:
        assert "GetQuarterlyPerformanceRating(cid, 0)" not in self._snapshot_block()

    def test_it_asks_for_the_last_completed_quarter(self) -> None:
        assert "GetQuarterlyPerformanceRating(cid, 1)" in self._snapshot_block()

    def test_company_value_still_asks_for_the_current_quarter(self) -> None:
        """Deliberately different, and the reason is easy to lose. Company value is not
        a rating: the current quarter answers it correctly, and the same live probe that
        returned -1 for the rating returned 1 for the value."""
        from pathlib import Path

        source = Path(__file__).parent.parent / "ottd_config" / "game" / "nttd-gs" / "main.nut"
        assert "GetQuarterlyCompanyValue(cid, 0)" in source.read_text()

    def test_the_score_version_moved_off_the_one_that_never_scored(self) -> None:
        from nttd.analysis.score import SCORE_VERSION

        assert SCORE_VERSION != "v1"
