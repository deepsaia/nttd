"""Every field the Gym encoder reads is a field a snapshot actually has.

The bug this exists for: ``NttdEnv._encode`` read ``company["expenses"]``, and no snapshot has
ever contained that key. The GameScript emits ``q0_expenses`` from
``GSCompany.GetQuarterlyExpenses``, the Company schema has no plain ``expenses`` field, and
nothing filled one. Confirmed against a recorded session, whose company carried
``q0_expenses = -166`` and no ``expenses``.

Nothing failed, which is the point. ``company.get("expenses", 0) or 0`` cannot tell a missing
key from a genuine zero, so two of the ten observation dimensions were constant: expenses read
0 forever, and the profit margin degenerated to sign(income). An RL policy could not perceive
spending at all, and no error was ever raised.

Worth being clear about what this file does NOT test, because the obvious version of it is
worthless. HTTP, MCP and Gym cannot return different observations: there is one implementation,
the participant-tier HTTP route, and the other two are clients of it. ``rl/env.py`` posts with
``requests`` and ``mcp/participant_client.py`` gets with ``httpx``, both to
``/v1/participant/sessions/{id}/state/*``. Asserting they agree would assert that HTTP equals
HTTP. What can and did diverge is the PROJECTION each client applies afterwards, and that is
what is checked here.
"""

from __future__ import annotations

import numpy as np
import pytest

from nttd.rl.env import NttdEnv
from nttd.schemas.company import Company
from tests.conftest import REPO_ROOT

# The keys the GameScript's CmdGetCompanies emits, plus the two apply_gs_company_finance fills
# from get_company_finance. Taken from main.nut and state/world.py rather than invented, since
# inventing the payload is what made the original bug invisible: a fixture with an "expenses"
# key would have let the broken code pass.
_COMPANY_FROM_A_REAL_RUN = {
    "id": 0,
    "name": "velvet-cloud-31d5",
    "money": 99118,
    "loan": 100000,
    "max_loan": 300000,
    "performance_rating": 30,
    "q0_income": 84000,
    "q0_expenses": -21000,   # negative, as OpenTTD reports it
    "q0_cargo": 240,
    "income": 76000,         # q1_income, the last completed quarter
    "value": 1809,           # q1_value
    "profit_last_year": 0,
    "color": 0,
    "is_ai": False,
    "is_active": True,
}


def _env() -> NttdEnv:
    env = NttdEnv.__new__(NttdEnv)
    env.company_id = 0
    env._start_date = 0
    return env


def _snapshot(company: dict) -> dict:
    return {
        "game": {"game_date": 365},
        "companies": [company],
        "vehicles": [{"company_id": 0}] * 4,
        "stations": [{"company_id": 0}] * 3,
        "towns": [{}] * 20,
    }


def test_the_encoder_reads_no_field_a_company_does_not_have() -> None:
    """The guard for the whole class, not just the one instance.

    Every key the encoder pulls from a company must be either in the Company schema or in the
    set the GameScript emits. A read of anything else silently yields the default forever.
    """

    source = (REPO_ROOT / "src" / "nttd" / "rl" / "env.py").read_text()
    encode = source.split("def _encode(")[1]

    # company.get("<name>"...) inside _encode
    reads = set()
    for fragment in encode.split('company.get("')[1:]:
        reads.add(fragment.split('"')[0])

    available = set(Company.model_fields) | {"q0_income", "q0_expenses", "q0_cargo", "hq_x", "hq_y"}
    unknown = sorted(reads - available)
    assert not unknown, (
        f"_encode reads {unknown} from a company, which no snapshot provides. Each returns its "
        f"default silently, so the dimension it feeds is constant. Check the keys "
        f"CmdGetCompanies emits in main.nut."
    )


def test_expenses_reach_the_observation() -> None:
    """The specific regression. This dimension was 0.0 for every run ever recorded."""
    observation, _ = _env()._encode(_snapshot(_COMPANY_FROM_A_REAL_RUN))
    expenses_dimension = observation[3]

    assert expenses_dimension != 0.0, "expenses are back to reading as zero"
    # 21,000 spent, scaled by 100,000, as a positive magnitude.
    assert expenses_dimension == pytest.approx(0.21)


def test_the_margin_is_a_margin_and_not_the_sign_of_income() -> None:
    """It used to compute (income - expenses)/|income| against an absent expenses, which is
    sign(income): 1.0 for any profitable quarter, whatever the costs.

    Also covers the sign convention. Expenses are negative, so profit is income PLUS expenses;
    subtracting them would report costs as earnings and rank a wasteful company higher.
    """
    observation, _ = _env()._encode(_snapshot(_COMPANY_FROM_A_REAL_RUN))
    margin = observation[5]

    # (84,000 + -21,000) / 84,000
    assert margin == pytest.approx(0.75)
    assert margin != 1.0, "the margin is still just the sign of income"


def test_a_company_that_spent_more_than_it_earned_reports_a_negative_margin() -> None:
    """The case that separates a real margin from a sign: costs above earnings."""
    losing = dict(_COMPANY_FROM_A_REAL_RUN, q0_income=10_000, q0_expenses=-30_000)
    observation, _ = _env()._encode(_snapshot(losing))

    assert observation[5] == pytest.approx(-2.0)


def test_every_observation_dimension_can_move() -> None:
    """Two dimensions were constant for the life of the project. A dimension that never
    changes is worse than an absent one: it costs a policy capacity and teaches it nothing.
    """
    poor = dict(_COMPANY_FROM_A_REAL_RUN, money=1000, loan=0, q0_income=0, q0_expenses=0,
                income=0, value=0)
    rich = dict(_COMPANY_FROM_A_REAL_RUN, money=9_000_000, loan=300_000, q0_income=500_000,
                q0_expenses=-100_000, income=400_000, value=8_000_000)

    low, _ = _env()._encode(_snapshot(poor))
    high, _ = _env()._encode(_snapshot(rich))

    unmoved = [index for index in range(len(low)) if low[index] == high[index]]
    # Vehicles, stations, towns and the elapsed year are the same in both fixtures by
    # construction, so only the six financial dimensions are asserted to respond.
    financial = [index for index in unmoved if index in {0, 1, 2, 3, 4, 5}]
    assert not financial, f"financial dimensions {financial} did not respond to the company"


def test_the_observation_stays_inside_the_declared_space() -> None:
    """The Box spans -10 to 10, and a negative margin now genuinely occurs, so the bound
    matters in a way it did not while the margin was pinned at 1.0."""
    losing = dict(_COMPANY_FROM_A_REAL_RUN, q0_income=10_000, q0_expenses=-30_000)
    observation, _ = _env()._encode(_snapshot(losing))

    assert np.all(observation >= -10.0)
    assert np.all(observation <= 10.0)
