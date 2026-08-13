"""Chart geometry and escaping.

The axis arithmetic is the part of a chart worth testing, because none of it is visible by
looking at the finished picture: a wrong tick is still a plausible looking plot.
"""

from __future__ import annotations

from typing import Any

from nttd.monitor.charts import esc, line_chart, mix_bars, number, panel, table
from nttd.monitor.scale import Scale


def _series(values: list[Any]) -> list[dict[str, Any]]:
    return [{
        "label": "s",
        "colour": "#4f8cff",
        "rows": [{"step": i, "v": v} for i, v in enumerate(values)],
    }]


# ---------------------------------------------------------------- Scale


def test_a_flat_series_does_not_divide_by_zero() -> None:
    """Every count chart starts flat at zero, so this is the common case, not the edge."""
    scale = Scale(0, 0, 0, 0, 460, 200, 54, 14, 12, 26)
    assert scale.x(0) == 54
    assert 12 <= scale.y(0) <= 200


def test_counts_get_whole_number_ticks() -> None:
    """A range of 0 to 2 was getting ticks every 0.5, which the label formatter rounded,
    printing the same number twice."""
    ticks = Scale(0, 30, 0, 2, 460, 200, 54, 14, 12, 26, integral=True).ticks(4)
    assert ticks == [0.0, 1.0, 2.0]
    assert len(set(ticks)) == len(ticks)


def test_money_keeps_fractional_ticks_when_it_needs_them() -> None:
    ticks = Scale(0, 30, 0, 1, 460, 200, 54, 14, 12, 26).ticks(4)
    assert any(0 < t < 1 for t in ticks)


def test_ticks_stay_inside_the_range_they_cover() -> None:
    scale = Scale(0, 30, 28, 31, 460, 200, 54, 14, 12, 26, integral=True)
    ticks = scale.ticks(4)
    assert ticks
    assert min(ticks) >= 28
    assert max(ticks) <= 31


# ---------------------------------------------------------------- line_chart


def test_a_chart_with_no_points_says_so_rather_than_drawing_nothing() -> None:
    out = line_chart("c", _series([None, None]), "Rating", "v")
    assert "no data" in out
    assert "<polyline" not in out


def test_a_single_point_is_drawn_as_a_dot() -> None:
    """One step in is the state of every session for its first minute."""
    out = line_chart("c", _series([5]), "Rating", "v")
    assert "<circle" in out
    assert "<polyline" not in out


def test_a_missing_value_leaves_a_gap_rather_than_a_zero() -> None:
    """Plotting a missing figure as zero would read as a real collapse."""
    out = line_chart("c", _series([10, None, 12]), "Rating", "v")
    assert out.count(",") >= 1
    assert "<polyline" in out


def test_booleans_are_not_plotted_as_numbers() -> None:
    """isinstance(True, int) is true in Python, so this needs an explicit guard."""
    out = line_chart("c", _series([True, False]), "Flag", "v")
    assert "no data" in out


def test_the_geometry_the_script_layer_reads_is_embedded() -> None:
    out = line_chart("cid1", _series([1, 2, 3]), "Rating", "v")
    assert "data-geom=" in out
    assert "xmin" in out and "series" in out


# ---------------------------------------------------------------- panels


def test_a_span_becomes_a_grid_class() -> None:
    assert 'class="plot"' in panel("t", "x")
    assert "plot two" in panel("t", "x", span="two")
    assert "plot full" in panel("t", "x", span="full")


def test_an_empty_table_still_renders_its_panel() -> None:
    out = table(["a"], [], "Actions", "nothing submitted yet")
    assert "nothing submitted yet" in out
    assert "<table" not in out


def test_mix_bars_shows_successes_against_refusals() -> None:
    out = mix_bars("m", [("build_dock", 3, 2)], "Actions")
    assert "3/5" in out
    assert "seg good" in out and "seg bad" in out


def test_mix_bars_with_nothing_submitted_says_so() -> None:
    assert "no actions submitted" in mix_bars("m", [], "Actions")


# ---------------------------------------------------------------- escaping


def test_session_names_cannot_inject_markup() -> None:
    """Session names and error strings reach the page, and an error can carry anything."""
    assert "<script>" not in esc("<script>alert(1)</script>")
    assert "&lt;script&gt;" in esc("<script>alert(1)</script>")


def test_none_renders_as_a_dash_rather_than_the_word_none() -> None:
    assert number(None) == "-"


def test_large_figures_are_abbreviated() -> None:
    assert number(1_500_000) == "1.50M"
    assert number(28_200) == "28.2k"
    assert number(30) == "30"
