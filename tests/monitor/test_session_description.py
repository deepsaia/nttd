"""A scenario's description says what the run is for, and the monitor shows it.

The monitor lists a wall of near-identical generated names and ids. Nothing on the page said
which one was the rail attempt and which was the combined one.

The description is the scenario's own, already a field on ScenarioConfig and previously read
and then dropped. Creating a session copies it onto the session record, so the page can show
it without reopening the config file. Optional throughout: a scenario that sets none produces
a session with none, and nothing renders.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nttd.analysis.loader import SessionData


def _session(meta: dict[str, Any]) -> SessionData:
    return SessionData(session_id="ses_x", session_dir=Path("/tmp/ses_x"), meta=meta)


def test_the_description_is_read_from_the_session_record() -> None:
    assert _session({"description": "a rail-focussed gameplay"}).description == (
        "a rail-focussed gameplay"
    )


def test_a_session_without_one_reports_empty_rather_than_failing() -> None:
    """Every session recorded before this existed has no description at all."""
    assert _session({}).description == ""
    assert _session({"description": None}).description == ""


def test_a_scenario_may_declare_one_and_may_leave_it_out() -> None:
    """Optional on the scenario, which is why nothing in config/benchmark had to change."""
    from nttd.config.scenario_config import ScenarioConfig

    assert ScenarioConfig().description == ""
    assert ScenarioConfig(description="a water-focussed gameplay").description == (
        "a water-focussed gameplay"
    )


def test_the_monitor_puts_the_aim_beside_the_name() -> None:
    from nttd.monitor import page

    meta = {
        "session_id": "ses_x", "name": "ivory-orchid-20260814-110422ist", "live": True,
        "end_reason": "", "description": "a rail-focussed gameplay",
    }
    rendered = page._session_header(meta)
    assert "ivory-orchid-20260814-110422ist" in rendered
    assert "a rail-focussed gameplay" in rendered
    # Beside the title, and before the id that is pushed to the far right.
    assert rendered.index("ivory-orchid") < rendered.index("rail-focussed")
    assert rendered.index("rail-focussed") < rendered.index("ses_x")


def test_a_session_without_an_aim_renders_no_empty_element() -> None:
    from nttd.monitor import page

    rendered = page._session_header(
        {"session_id": "ses_x", "name": "n", "live": False, "end_reason": "manual"},
    )
    assert 'class="aim"' not in rendered
