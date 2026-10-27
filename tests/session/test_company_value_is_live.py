"""The observed company value is the live one, not the last quarter's."""

from nttd.state.world import WorldState


def test_finance_refresh_keeps_the_live_company_value():
    world = WorldState()
    world.apply_gs_companies([{"id": 0, "name": "Team", "money": 100000, "loan": 100000, "company_value": 1}])
    world.apply_gs_company_finance(0, {"balance": 100000, "loan": 100000, "q1_income": 0, "q1_value": 0})
    assert world.companies[0].value == 1
    assert world.companies[0].income == 0
