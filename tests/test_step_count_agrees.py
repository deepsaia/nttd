"""Every place that shows a step count shows the same number.

Four places on one page reported the step count: the sidebar sub-text, the KPI card, the index
table, and the World map's scrubber. The scrubber disagreed with the other three, for two
independent reasons:

  * It labelled the slider's zero-based INDEX, so a 366 step run read "step 365".
  * Its frames come from the parsed snapshots, while the count came from the raw rows. Those
    differ whenever a fragment is torn, which happens while another process is writing.

Fixed by counting parsed snapshots in one place and labelling the scrubber 1-based. These tests
pin both halves, because either one alone reintroduces the mismatch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nttd.analysis.loader import SessionData
from nttd.monitor.session_feed import SessionFeed


def _feed(snapshots: list[dict[str, Any]], junk: int = 0) -> SessionFeed:
    import polars as pl

    rows = [json.dumps(s) for s in snapshots] + ["{not json"] * junk
    frame = pl.DataFrame({"snapshot_json": rows})
    data = SessionData(session_id="ses_x", session_dir=Path("/tmp/ses_x"), snapshots=frame)
    return SessionFeed(data)


def _snapshot(day: int) -> dict[str, Any]:
    return {"game": {"game_date": day, "map_width": 256, "map_height": 256},
            "companies": [{"name": "c", "performance_rating": 1}],
            "stations": [], "vehicles": []}


def test_the_count_matches_the_number_of_charted_steps() -> None:
    feed = _feed([_snapshot(d) for d in range(737790, 737800)])
    assert feed.meta()["steps"] == len(feed.steps())


def test_the_count_matches_the_map_scrubber_frames() -> None:
    """The scrubber's last position plus one must equal the reported count."""
    feed = _feed([_snapshot(d) for d in range(737790, 737800)])
    frames = feed.dynamic_world()
    assert feed.meta()["steps"] == len(frames)


def test_a_torn_row_is_excluded_from_every_count_or_from_none() -> None:
    """The bug: raw rows counted 12, parsed frames held 10, and the page showed both."""
    feed = _feed([_snapshot(d) for d in range(737790, 737800)], junk=2)
    assert feed.meta()["steps"] == len(feed.dynamic_world()) == len(feed.steps()) == 10


def test_the_scrubber_label_is_one_based() -> None:
    from nttd.monitor import worldmap

    rendered = worldmap._scrubber([{"game_date": 737790}, {"game_date": 737791}])
    assert "step 2" in rendered, "two frames is two steps, not one"
    assert 'max="1"' in rendered, "the slider itself stays zero-based"


def test_the_live_page_refreshes_every_five_seconds() -> None:
    from nttd.monitor import page

    assert page.LIVE_REFRESH_SECONDS == 5
    assert 'content="5"' in page.shell("x", refresh=page.LIVE_REFRESH_SECONDS)
