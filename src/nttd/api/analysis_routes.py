"""Analysis API endpoints -- serve report data and plots for frontend."""

import io
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from nttd.analysis.loader import load_session
from nttd.analysis.reports.registry import ensure_reports_loaded, get_report, list_reports

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/{session_id}/reports")
async def get_available_reports(session_id: str) -> dict[str, Any]:
    """List all available report names."""
    ensure_reports_loaded()
    return {"session_id": session_id, "reports": list_reports()}


@router.get("/{session_id}/report/{report_name}")
async def get_report_data(
    session_id: str,
    report_name: str,
    compare: str | None = None,
) -> dict[str, Any]:
    """Run a single report and return its structured data as JSON.

    Optionally compare with additional sessions (comma-separated IDs).
    """
    ensure_reports_loaded()
    try:
        gen = get_report(report_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown report: {report_name}")

    session_ids = [session_id]
    if compare:
        session_ids.extend(s.strip() for s in compare.split(",") if s.strip())

    try:
        sessions = [load_session(sid) for sid in session_ids]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    result = gen(sessions)
    return {
        "name": result.name,
        "title": result.title,
        "data": result.data,
        "figures": [name for name, _ in result.figures],
        "markdown": result.markdown,
    }


@router.get("/{session_id}/report/{report_name}/plot/{plot_name}")
async def get_report_plot(
    session_id: str,
    report_name: str,
    plot_name: str,
    fmt: str = "png",
    compare: str | None = None,
) -> Response:
    """Return a specific plot from a report as PNG or HTML.

    Query params:
      fmt: "png" (default) or "html"
      compare: comma-separated additional session IDs
    """
    ensure_reports_loaded()
    try:
        gen = get_report(report_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown report: {report_name}")

    session_ids = [session_id]
    if compare:
        session_ids.extend(s.strip() for s in compare.split(",") if s.strip())

    try:
        sessions = [load_session(sid) for sid in session_ids]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    result = gen(sessions)

    for fig_name, fig in result.figures:
        if fig_name == plot_name:
            if fmt == "html":
                html = fig.to_html(include_plotlyjs="cdn")
                return Response(content=html, media_type="text/html")
            else:
                buf = io.BytesIO()
                height = fig.layout.height or 500
                fig.write_image(buf, format="png", scale=2, width=1200, height=height)
                buf.seek(0)
                return Response(content=buf.read(), media_type="image/png")

    raise HTTPException(
        status_code=404,
        detail=f"Plot '{plot_name}' not found in report '{report_name}'. "
               f"Available: {[n for n, _ in result.figures]}",
    )
