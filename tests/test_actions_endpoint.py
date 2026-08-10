"""Publishing the action manifest over HTTP.

The manifest already backs the validator, `nttd actions` and `docs/actions/`. This is the
route an agent should use instead of any of them: the shape is already structured, so
nothing has to parse markdown and be approximately right about it.

Public tier rather than participant, because the manifest describes the build rather than
a session. An agent working out what it can do should not have to start a game first.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nttd.api.app import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


class TestItAnswersWithoutASession:
    def test_the_manifest_is_served_on_the_public_tier(self, client: TestClient) -> None:
        """No session, no token, no game running."""
        response = client.get("/v1/public/actions")
        assert response.status_code == 200
        assert response.json()["count"] > 0

    def test_it_says_which_build_the_constants_came_from(self, client: TestClient) -> None:
        """The enum values are read from an OpenTTD build. A client caching them wants to
        know when that build changed."""
        body = client.get("/v1/public/actions").json()
        assert body["enum_values_from"]
        assert body["generated_from"].endswith("main.nut")


class TestOperatorActionsAreLeftOutButNotHidden:
    def test_they_are_absent_by_default(self, client: TestClient) -> None:
        """No session can run one, so returning them by default hands every caller nine
        actions that only ever fail."""
        actions = client.get("/v1/public/actions").json()["actions"]
        assert "found_town" not in actions
        assert "change_bank_balance" not in actions

    def test_the_reply_says_what_it_left_out(self, client: TestClient) -> None:
        """A filtered response that does not admit to filtering reads as the whole
        surface, and a client would have no reason to look further."""
        body = client.get("/v1/public/actions").json()
        assert body["excluded"]["tier"] == "operator"
        assert body["excluded"]["count"] == 9
        assert "tier=operator" in body["excluded"]["reason"]

    def test_asking_for_them_returns_them(self, client: TestClient) -> None:
        body = client.get("/v1/public/actions", params={"tier": "operator"}).json()
        assert body["count"] == 9
        assert "found_town" in body["actions"]

    def test_an_explicit_tier_does_not_claim_an_exclusion(self, client: TestClient) -> None:
        """The note is about the default. Repeating it when the caller chose the filter
        would be telling them what they just asked for."""
        assert "excluded" not in client.get(
            "/v1/public/actions", params={"tier": "participant"},
        ).json()


class TestFiltering:
    @pytest.mark.parametrize(
        ("tier", "expected"), [("read_only", 44), ("participant", 77), ("operator", 9)],
    )
    def test_by_tier(self, client: TestClient, tier: str, expected: int) -> None:
        body = client.get("/v1/public/actions", params={"tier": tier}).json()
        assert body["count"] == expected
        assert {e["tier"] for e in body["actions"].values()} == {tier}

    def test_by_category(self, client: TestClient) -> None:
        body = client.get("/v1/public/actions", params={"category": "rail"}).json()
        assert body["count"] > 0
        assert {e["category"] for e in body["actions"].values()} == {"rail"}

    def test_an_unknown_filter_returns_nothing_rather_than_everything(
        self, client: TestClient,
    ) -> None:
        """Silently ignoring a filter it does not understand would return the whole
        manifest and look like a match."""
        assert client.get(
            "/v1/public/actions", params={"category": "monorail"},
        ).json()["count"] == 0


class TestOneAction:
    def test_it_carries_everything_needed_to_call_it(self, client: TestClient) -> None:
        body = client.get("/v1/public/actions/build_road_stop").json()
        assert body["action_type"] == "build_road_stop"
        assert body["description"]
        assert body["parameters"]["is_truck_stop"]["type"] == "boolean"
        assert [["tile"], ["x", "y"]] in body["one_of"]

    def test_the_accepted_constants_come_with_it(self, client: TestClient) -> None:
        """Without these the parameter is an integer and which integer is the whole
        question."""
        body = client.get("/v1/public/actions/set_order_condition").json()
        values = body["parameters"]["condition"]["enum"]["values"]
        assert values["OC_UNCONDITIONALLY"] == 5
        assert body["parameters"]["condition"]["enum"]["class"] == "GSOrder"

    def test_an_operator_action_is_still_readable_by_name(self, client: TestClient) -> None:
        """Left out of the listing, not withheld. Someone authoring a scenario has a
        reason to read one."""
        assert client.get("/v1/public/actions/found_town").status_code == 200

    def test_an_unknown_action_suggests_the_nearest(self, client: TestClient) -> None:
        """A bare 404 makes an agent fetch the whole manifest to find out what it meant."""
        response = client.get("/v1/public/actions/build_road_stopp")
        assert response.status_code == 404
        assert "build_road_stop" in response.json()["detail"]["did_you_mean"]


class TestItAgreesWithTheOtherSurfaces:
    def test_it_serves_what_the_validator_enforces(self, client: TestClient) -> None:
        """Two descriptions of the same action would be worse than one: an agent would
        follow the published one and be refused by the enforced one."""
        from nttd.config import action_manifest

        body = client.get("/v1/public/actions", params={"tier": "participant"}).json()
        for name, entry in body["actions"].items():
            assert sorted(entry["parameters"]) == action_manifest.accepted_parameters(name)
            assert entry.get("one_of", []) == action_manifest.alternatives(name)

    def test_every_published_action_would_validate_if_called(
        self, client: TestClient,
    ) -> None:
        """Publishing an action the validator refuses outright would be advertising
        something unusable."""
        from nttd.constants import OPERATOR_ACTIONS

        body = client.get("/v1/public/actions", params={"tier": "participant"}).json()
        assert not set(body["actions"]) & OPERATOR_ACTIONS


def test_the_legacy_unprefixed_path_does_not_serve_this(client: TestClient) -> None:
    """A new route should land in a tier deliberately. The unprefixed paths exist for
    callers written before the tiers did, and this had none."""
    assert client.get("/actions").status_code == 404


def test_it_is_mounted_on_the_public_tier_only() -> None:
    paths = [r.path for r in app.routes if getattr(r, "path", "").endswith("/actions")]
    assert "/v1/public/actions" in paths
    assert not [p for p in paths if p.startswith(("/v1/participant", "/v1/operator"))]
