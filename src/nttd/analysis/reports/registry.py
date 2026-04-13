"""Report registry: central catalog of available report generators.

Each report module exposes a ``generate(sessions)`` function that returns a
ReportResult. The registry maps short names to those callables so the CLI
and API can discover and run them by name.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import plotly.graph_objects as go

from nttd.analysis.date_utils import game_date_to_str
from nttd.analysis.loader import SessionData

logger = logging.getLogger(__name__)


@dataclass
class ReportResult:
    """Output of a single report generator."""

    name: str
    title: str
    data: dict[str, Any] = field(default_factory=dict)
    figures: list[tuple[str, go.Figure]] = field(default_factory=list)
    markdown: str = ""
    files: list[tuple[str, Path]] = field(default_factory=list)


ReportGenerator = Callable[[list[SessionData]], ReportResult]

_REGISTRY: dict[str, ReportGenerator] = {}


def register(name: str) -> Callable[[ReportGenerator], ReportGenerator]:
    """Decorator to register a report generator under *name*."""

    def wrapper(func: ReportGenerator) -> ReportGenerator:
        _REGISTRY[name] = func
        return func

    return wrapper


def list_reports() -> list[str]:
    """Return all registered report names."""
    ensure_reports_loaded()
    return list(_REGISTRY.keys())


def get_report(name: str) -> ReportGenerator:
    """Look up a registered report by name. Raises KeyError if unknown."""
    return _REGISTRY[name]


def ensure_reports_loaded() -> None:
    """Import all report modules so they register via the @register decorator.

    Safe to call multiple times -- modules are only imported once by Python.
    """
    from nttd.analysis.reports import (  # noqa: F401
        action_analysis,
        agent_performance,
        cargo_delivery,
        cargo_distances,
        cargo_routes,
        events_timeline,
        financial,
        infrastructure,
        orders,
        route_completion,
        session_summary,
        tile_map,
        vehicle_fleet,
        video,
        world_state,
    )


def _period_context(sessions: list[SessionData]) -> dict[str, Any]:
    """Extract game-date period from sessions for report headers."""
    date_from: int | None = None
    date_to: int | None = None
    for s in sessions:
        if s.snapshots.is_empty() or "game_date" not in s.snapshots.columns:
            continue
        mn = int(s.snapshots["game_date"].min())
        mx = int(s.snapshots["game_date"].max())
        date_from = mn if date_from is None else min(date_from, mn)
        date_to = mx if date_to is None else max(date_to, mx)

    if date_from is None or date_to is None:
        return {}

    return {
        "date_from": date_from,
        "date_to": date_to,
        "date_from_str": game_date_to_str(date_from),
        "date_to_str": game_date_to_str(date_to),
        "total_days": date_to - date_from,
    }


def _inject_period(result: ReportResult, period: dict[str, Any]) -> None:
    """Inject period context into a ReportResult's markdown, data, and figures."""
    if not period:
        return

    header = (
        f"> Period: **{period['date_from_str']}** to **{period['date_to_str']}** "
        f"({period['total_days']} game days)\n"
    )

    # Inject into markdown after the first heading line
    if result.markdown:
        lines = result.markdown.split("\n", 1)
        if len(lines) == 2:
            result.markdown = lines[0] + "\n" + header + "\n" + lines[1]
        else:
            result.markdown = lines[0] + "\n" + header

    # Inject into data dict
    result.data["period"] = period

    # Inject as subtitle annotation on all figures
    subtitle = (
        f"Period: {period['date_from_str']} -- {period['date_to_str']} "
        f"({period['total_days']} days)"
    )
    for _, fig in result.figures:
        if fig is not None:
            fig.update_layout(
                title_subtitle_text=subtitle,
                title_subtitle_font_size=11,
                title_subtitle_font_color="gray",
            )


def run_reports(
    sessions: list[SessionData],
    report_names: list[str] | None = None,
) -> list[ReportResult]:
    """Run selected (or all) reports and return their results.

    Ensures all report modules are imported first. Skips reports that raise
    exceptions, logging the error. Injects game-date period into every result.
    """
    ensure_reports_loaded()
    period = _period_context(sessions)
    names = report_names or list(_REGISTRY.keys())
    results: list[ReportResult] = []
    for name in names:
        gen = _REGISTRY.get(name)
        if gen is None:
            logger.warning("Unknown report '%s', skipping", name)
            continue
        try:
            result = gen(sessions)
            _inject_period(result, period)
            results.append(result)
        except Exception:
            logger.exception("Report '%s' failed", name)
    return results
