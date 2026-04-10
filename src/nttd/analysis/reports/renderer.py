"""Output renderers: write ReportResults to markdown, images, JSON, or HTML."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from nttd.analysis.reports.registry import ReportResult

logger = logging.getLogger(__name__)


class _JSONEncoder(json.JSONEncoder):
    """Handle non-serializable types gracefully."""

    def default(self, o: Any) -> Any:
        if hasattr(o, "isoformat"):
            return o.isoformat()
        if hasattr(o, "__dict__"):
            return str(o)
        return super().default(o)


def render_markdown(results: list[ReportResult], output_path: Path) -> Path:
    """Write all report markdown into a single combined file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sections: list[str] = []
    for r in results:
        if r.markdown:
            sections.append(r.markdown)

    output_path.write_text("\n---\n\n".join(sections), encoding="utf-8")
    logger.info("Wrote markdown report to %s", output_path)
    return output_path


def render_plots(
    results: list[ReportResult],
    output_dir: Path,
    fmt: str = "png",
) -> list[Path]:
    """Save all figures from all reports as image or HTML files.

    Returns list of written file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for r in results:
        for fig_name, fig in r.figures:
            filename = f"{r.name}_{fig_name}"
            if fmt == "html":
                path = output_dir / f"{filename}.html"
                fig.write_html(str(path))
            else:
                path = output_dir / f"{filename}.png"
                height = fig.layout.height or 500
                try:
                    fig.write_image(str(path), scale=2, width=1200, height=height)
                except Exception:
                    logger.warning("Failed to write %s (kaleido may not be available)", path)
                    continue

            written.append(path)
            logger.info("Wrote %s", path)

    return written


def render_json(results: list[ReportResult], output_path: Path) -> Path:
    """Write structured report data as a JSON file (for frontend consumption)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "reports": [
            {
                "name": r.name,
                "title": r.title,
                "data": r.data,
                "figures": [name for name, _ in r.figures],
            }
            for r in results
        ]
    }
    output_path.write_text(
        json.dumps(payload, indent=2, cls=_JSONEncoder),
        encoding="utf-8",
    )
    logger.info("Wrote JSON report to %s", output_path)
    return output_path


def render_all(
    results: list[ReportResult],
    output_dir: Path,
    formats: list[str] | None = None,
) -> list[Path]:
    """Render reports in all requested formats. Returns all written file paths.

    Supported format strings: "markdown", "png", "html", "json".
    """
    if formats is None:
        formats = ["markdown", "png"]

    written: list[Path] = []

    if "markdown" in formats:
        md_path = output_dir / "report.md"
        written.append(render_markdown(results, md_path))

    if "png" in formats:
        plots_dir = output_dir / "plots"
        written.extend(render_plots(results, plots_dir, fmt="png"))

    if "html" in formats:
        plots_dir = output_dir / "plots"
        written.extend(render_plots(results, plots_dir, fmt="html"))

    if "json" in formats:
        json_path = output_dir / "report.json"
        written.append(render_json(results, json_path))

    # Collect file artifacts (e.g. video) -- already written by the report generator
    for r in results:
        for _name, fpath in r.files:
            if fpath.exists():
                written.append(fpath)

    return written
