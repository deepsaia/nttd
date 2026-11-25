"""An operator capital grant must preserve debt, revenue, and the playing budget."""

from __future__ import annotations

import time

import httpx
import pytest

from tests.gameplay.test_station_cargo_acceptance_live import airport_world as airport_world

pytestmark = pytest.mark.gs_test


def test_initial_capital_grant_preserves_finance_and_unstarted_clock(
    airport_world: tuple[httpx.Client, str],
) -> None:
    client, sid = airport_world
    state_url = f"/v1/participant/sessions/{sid}/state/full"
    response = client.get(state_url)
    response.raise_for_status()
    before = response.json()
    company_before = next(company for company in before["companies"] if company["id"] == 0)
    assert company_before["money"] == 100_000
    assert company_before["loan"] == 100_000
    assert company_before["max_loan"] == 300_000
    assert company_before["q0_income"] == company_before["episode_revenue"] == 0
    budget = before["game"]["game_days_total"]
    assert budget > 0
    assert before["game"]["game_days_remaining"] == budget

    response = client.post(
        f"/v1/operator/admin/sessions/{sid}/deity/change_balance",
        json={"company_id": 0, "delta": 400_000},
    )
    assert response.status_code == 200, response.text
    assert response.json()["new_balance"] == 500_000

    # The full state is cached. Let the game advance and the cache refresh.
    # A wrongly started playing clock would consume budget during this wait.
    earliest_check = time.monotonic() + 4
    deadline = time.monotonic() + 30
    while True:
        response = client.get(state_url)
        response.raise_for_status()
        after = response.json()
        company_after = next(company for company in after["companies"] if company["id"] == 0)
        if (
            company_after["money"] == 500_000
            and company_after["value"] == 400_000
            and after["game"]["game_date"] > before["game"]["game_date"]
            and time.monotonic() >= earliest_check
        ):
            break
        assert time.monotonic() < deadline, after
        time.sleep(0.25)

    assert company_after["loan"] == company_before["loan"]
    assert company_after["max_loan"] == company_before["max_loan"]
    for field in ("q0_income", "q1_income", "episode_revenue", "cargo_delivered_total"):
        assert company_after[field] == company_before[field], (field, company_after)
    assert not after["vehicles"]
    assert not after["stations"]
    assert after["game"]["game_days_remaining"] == budget
