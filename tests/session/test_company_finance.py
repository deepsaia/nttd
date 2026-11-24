"""Quarter histories preserve units, completeness and independent company accounting."""

from unittest.mock import Mock

from pyopenttdadmin.packet import CompanyEconomyPacket

from nttd.bridge.bridge import Bridge
from nttd.state.finance import RevenueLedger
from nttd.state.world import WorldState


def finance(quarter, current, history):
    return {"finance_date": 715875, "finance_quarter": quarter, "q0_income": current,
            "q1_income": history[0] if history else 0, "completed_quarter_income": history}


def test_ledger_excludes_opening_revenue_and_uses_completed_quarters():
    ledger = RevenueLedger()
    assert ledger.observe(20, 100, []) == 0
    assert ledger.observe(20, 180, []) == 80
    assert ledger.observe(20, 170, []) == 70  # A correction is not a quarter rollover.
    assert ledger.observe(21, 400, [300]) == 600  # q0 need not fall at rollover.
    assert ledger.observe(23, 500, [600, 450, 300]) == 1750


def test_ledger_missing_history_is_unknown_and_can_recover():
    ledger = RevenueLedger()
    assert ledger.observe(20, 100, []) == 0
    assert ledger.observe(23, 400, [600, 450]) is None
    assert ledger.observe(23, 500, [600, 450, 300]) == 1750
    assert ledger.observe(19, 200, []) is None


def test_both_finance_refresh_paths_share_one_ledger_per_company():
    world = WorldState()
    world.apply_gs_companies([
        {"id": 0, "name": "A", **finance(20, 100, [])},
        {"id": 1, "name": "B", **finance(20, 400, [])},
    ])
    assert world.companies[0].episode_revenue == world.companies[1].episode_revenue == 0
    world.apply_gs_company_finance(0, finance(21, 30, [300]))
    world.apply_gs_company_finance(1, finance(21, 60, [800]))
    assert world.companies[0].episode_revenue == 230
    assert world.companies[1].episode_revenue == 460
    world.apply_gs_companies([
        {"id": 0, "name": "A", **finance(21, 40, [300])},
        {"id": 1, "name": "B", **finance(21, 60, [800])},
    ])
    assert world.companies[0].episode_revenue == 240
    assert world.companies[0].income == world.companies[0].q1_income == 300
    assert world.snapshot().companies[0].completed_quarter_income == [300]


def test_missing_quarter_blocks_live_total_and_recreated_company_gets_new_baseline():
    world = WorldState()
    world.apply_gs_companies([{"id": 0, "name": "A", **finance(20, 100, [])}])
    world.apply_gs_company_finance(0, finance(22, 60, [800]))
    assert world.companies[0].episode_revenue is None
    world.apply_gs_companies([])
    world.apply_gs_companies([{"id": 0, "name": "B", **finance(22, 200, [800])}])
    assert world.companies[0].episode_revenue == 0


def test_admin_annual_cash_flow_cannot_overwrite_live_value_or_quarter_revenue():
    world = WorldState()
    world.apply_gs_companies([{"id": 0, "name": "A", "company_value": 12345,
                              **finance(21, 400, [300])}])
    packet = CompanyEconomyPacket(
        id=0, money=(1 << 64) - 10, current_loan=100000, income=(1 << 64) - 20000,
        delivered_cargo=200,
        quarterly_info=[{"value": 100, "performance": 1, "delivered_cargo": 5},
                        {"value": 80, "performance": 0, "delivered_cargo": 2}],
    )
    Bridge(world, Mock())._on_company_economy(packet)
    company = world.companies[0]
    assert (company.money, company.loan, company.annual_net_income) == (-10, 100000, -20000)
    assert (company.value, company.income, company.q0_income) == (12345, 300, 400)
    assert company.profit_last_year is None
    assert company.episode_revenue == 0
