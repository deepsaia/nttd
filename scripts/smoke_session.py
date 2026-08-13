"""Play the smallest possible game against a running nttd, and report whether it worked.

Answers one question that nothing else did: can this machine actually run a session? The test
suite deliberately needs no OpenTTD, the packaging check only proves the data files ship, and
the live GameScript suite needs a session handed to it. So every automated check passed on a
machine where starting a game was impossible, which is how nttd came to be macOS-only in
practice without anything noticing.

Small on purpose. A 128x128 map generates in seconds, and the run stops as soon as the
GameScript answers a query, because the thing in doubt is whether OpenTTD starts, loads the
GameScript and talks back, not whether a company can turn a profit.

    uv run python scripts/smoke_session.py [--base-url http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import sys
import time

import requests

# Generation is the slow part, and a cold container is slower than a warm laptop.
_START_TIMEOUT_SECONDS = 180.0
_POLL_SECONDS = 2.0

# Small, and old enough that every vehicle type exists. The same shape the live suite uses.
_SETTINGS = {
    "game_creation.map_x": "7",
    "game_creation.map_y": "7",
    "game_creation.starting_year": "1960",
    "difficulty.number_towns": "4",
    "game_creation.custom_town_number": "4",
}


def _create(base_url: str) -> str:
    reply = requests.post(
        f"{base_url}/v1/operator/admin/sessions/new",
        json={"name": "smoke_session"},
        timeout=30,
    )
    reply.raise_for_status()
    return str(reply.json()["session_id"])


def _start(base_url: str, session_id: str) -> None:
    requests.post(
        f"{base_url}/v1/operator/admin/sessions/{session_id}/settings",
        json={"settings": _SETTINGS},
        timeout=30,
    ).raise_for_status()
    requests.post(
        f"{base_url}/v1/operator/admin/sessions/{session_id}/start",
        json={"mode": "newgame", "ai_opponents": 0, "agent_companies": 1},
        timeout=120,
    ).raise_for_status()


def _wait_for_gamescript(base_url: str, session_id: str) -> dict:
    """Poll until the GameScript answers, then return the world it generated."""
    deadline = time.time() + _START_TIMEOUT_SECONDS
    last_error = "never answered"
    while time.time() < deadline:
        try:
            reply = requests.post(
                f"{base_url}/v1/operator/sessions/{session_id}/actions/gs/execute",
                params={"action": "get_map_size"},
                json={},
                timeout=30,
            )
            if reply.status_code == 200 and reply.json().get("success", True):
                return dict(reply.json().get("result") or {})
            last_error = f"HTTP {reply.status_code}"
        except requests.RequestException as exc:
            last_error = repr(exc)
        time.sleep(_POLL_SECONDS)
    raise TimeoutError(
        f"the GameScript did not answer within {_START_TIMEOUT_SECONDS:.0f}s: {last_error}",
    )


def _stop(base_url: str, session_id: str) -> None:
    """Best effort: a leaked OpenTTD outliving the run is worse than a noisy failure."""
    try:
        requests.post(
            f"{base_url}/v1/operator/admin/sessions/{session_id}/stop",
            params={"end_reason": "smoke_complete"},
            timeout=60,
        )
    except requests.RequestException as exc:
        print(f"warning: could not stop {session_id}: {exc!r}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    health = requests.get(f"{base_url}/health", timeout=30)
    health.raise_for_status()
    print(f"nttd is up at {base_url}")

    session_id = _create(base_url)
    print(f"created {session_id}")
    try:
        _start(base_url, session_id)
        print("OpenTTD spawned, waiting for the GameScript")
        size = _wait_for_gamescript(base_url, session_id)
        towns = requests.post(
            f"{base_url}/v1/operator/sessions/{session_id}/actions/gs/execute",
            params={"action": "get_towns"},
            json={},
            timeout=60,
        ).json()
        town_count = len(towns.get("result") or [])
    finally:
        _stop(base_url, session_id)

    print(f"the GameScript answered: map {size.get('size_x')}x{size.get('size_y')}, "
          f"{town_count} towns")
    if not size.get("size_x") or town_count < 1:
        print("a world was expected and did not arrive", file=sys.stderr)
        return 1
    print("a session can be played on this machine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
