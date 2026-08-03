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
    score = score_company(_company(0, performance_rating=740, q0_cargo=1200, value=50_000))
    assert score.primary == 740
    assert score.tiebreak == 1200
    assert score.score_version == SCORE_VERSION


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
    a = _company(0, performance_rating=600, q0_cargo=500)
    b = _company(1, performance_rating=600, q0_cargo=900)
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
