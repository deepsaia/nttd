"""Terrain-based video generation for session analysis.

Renders the tile terrain as a base image and overlays game objects
(towns, industries, stations, vehicles) from snapshots, showing
infrastructure appearing progressively over time.

Falls back to screenshot timelapse if no tile data is available.
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
from PIL import Image, ImageDraw, ImageFont

from nttd.analysis.date_utils import game_date_to_str
from nttd.analysis.reports.registry import ReportResult, register
from nttd.analysis.reports.terrain_palette import (
    COLOR_AIR,
    COLOR_HUD_BG_RGB,
    COLOR_HUD_TEXT_RGB,
    COLOR_INDUSTRY,
    COLOR_RAIL,
    COLOR_RAIL_LINE_RGB,
    COLOR_ROAD,
    COLOR_ROAD_LINE_RGB,
    COLOR_SHIP,
    COLOR_TOWN,
    LEGEND_ITEMS,
    TERRAIN_COLORSCALE,
    VEHICLE_COLORS,
    classify_station_type,
    prepare_terrain_grid,
)

if TYPE_CHECKING:
    from nttd.analysis.loader import SessionData

logger = logging.getLogger(__name__)

# Module-level config set by CLI before running reports
video_config: dict[str, int | str] = {
    "quality": "high",
    "fps": 4,
    "max_frames": 0,
}


@register("video")
def report_video(sessions: list[SessionData]) -> ReportResult:
    """Generate terrain video as a report. Saves MP4 to session reports dir."""
    session = sessions[0]
    quality = str(video_config.get("quality", "high"))
    fps = int(video_config.get("fps", 4))
    max_frames = int(video_config.get("max_frames", 0))
    try:
        video_path = generate_video(
            session, quality=quality, fps=fps, max_frames=max_frames,
        )
        return ReportResult(
            name="video",
            title="Game Progression Video",
            data={"video_path": str(video_path)},
            markdown=f"Video saved to `{video_path}`",
            files=[("game_progression", video_path)],
        )
    except (ImportError, FileNotFoundError) as exc:
        return ReportResult(
            name="video",
            title="Game Progression Video",
            data={"error": str(exc)},
            markdown=f"Video generation skipped: {exc}",
        )


@dataclass
class VideoQuality:
    """Video quality preset parameters."""

    scale: int
    crf: int
    preset: str
    hud_height: int
    font_main: int
    font_small: int
    marker_town: int
    marker_industry: int
    marker_station: int
    marker_vehicle: int
    line_width: int
    legend_marker: int


_QUALITY_PRESETS: dict[str, VideoQuality] = {
    "low": VideoQuality(
        scale=3, crf=28, preset="fast",
        hud_height=60, font_main=14, font_small=11,
        marker_town=5, marker_industry=4, marker_station=5, marker_vehicle=3,
        line_width=1, legend_marker=5,
    ),
    "medium": VideoQuality(
        scale=4, crf=23, preset="medium",
        hud_height=80, font_main=18, font_small=14,
        marker_town=7, marker_industry=5, marker_station=6, marker_vehicle=4,
        line_width=2, legend_marker=6,
    ),
    "high": VideoQuality(
        scale=10, crf=18, preset="slow",
        hud_height=120, font_main=24, font_small=18,
        marker_town=12, marker_industry=9, marker_station=11, marker_vehicle=6,
        line_width=4, legend_marker=9,
    ),
}


@dataclass
class InfraSegment:
    """A built infrastructure segment (rail or road line)."""

    x1: int
    y1: int
    x2: int
    y2: int
    infra_type: str  # "rail" or "road"
    game_date: int


def _build_base_terrain(
    tiles_df: object,
    scale: int,
) -> tuple[np.ndarray, int, int] | None:
    """Build terrain base image using Plotly's heatmap renderer.

    Renders the same Plotly heatmap used by tile_map.py (without
    axes/decorations), producing smooth high-res gradients via kaleido.
    Only runs once -- the result is reused for all video frames.

    Returns (rgb_array, max_x, max_y) or None if tiles are empty.
    """
    import plotly.graph_objects as go

    result = prepare_terrain_grid(tiles_df)
    if result is None:
        return None

    terrain, max_x, max_y = result

    fig = go.Figure(data=go.Heatmap(
        z=terrain,
        colorscale=TERRAIN_COLORSCALE,
        showscale=False,
    ))

    # Bare image -- no axes, no margins, no decorations
    target_w = max_x * scale
    target_h = max_y * scale
    fig.update_layout(
        xaxis=dict(
            visible=False, scaleanchor="y",
            constrain="domain", autorange="reversed",
        ),
        yaxis=dict(visible=False, autorange="reversed"),
        margin=dict(l=0, r=0, t=0, b=0),
        width=target_w,
        height=target_h,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    img_bytes = fig.to_image(format="png", width=target_w, height=target_h)
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    return np.array(img), max_x, max_y


def _tile_id_to_xy(tile_id: int, map_width: int) -> tuple[int, int]:
    """Convert OpenTTD tile ID to (x, y) coordinates."""
    x = tile_id % map_width
    y = tile_id // map_width
    return x, y


def _next_power_of_2(n: int) -> int:
    """Return the smallest power of 2 >= n."""
    p = 1
    while p < n:
        p *= 2
    return p


def _extract_infrastructure(
    actions_df: pl.DataFrame,
    map_width: int,
) -> list[InfraSegment]:
    """Extract infrastructure line segments from build actions."""
    segments: list[InfraSegment] = []
    if actions_df.is_empty():
        return segments

    infra_types = {
        "connect_rail": "rail",
        "connect_road": "road",
    }
    builds = actions_df.filter(
        pl.col("action_type").is_in(list(infra_types.keys()))
        & (pl.col("status") == "success")
    ).sort("game_date")

    for row in builds.iter_rows(named=True):
        try:
            params = json.loads(row["parameters_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        # connect_road/connect_rail use from_x/from_y/to_x/to_y coordinates
        if "from_x" in params and "to_x" in params:
            x1, y1 = int(params["from_x"]), int(params["from_y"])
            x2, y2 = int(params["to_x"]), int(params["to_y"])
        elif "tile_from" in params and "tile_to" in params:
            x1, y1 = _tile_id_to_xy(int(params["tile_from"]), map_width)
            x2, y2 = _tile_id_to_xy(int(params["tile_to"]), map_width)
        else:
            continue
        segments.append(InfraSegment(
            x1=x1, y1=y1, x2=x2, y2=y2,
            infra_type=infra_types[row["action_type"]],
            game_date=int(row["game_date"]),
        ))

    return segments


def _coord_to_pixel(
    x: int, y: int, max_x: int, scale: int,
) -> tuple[int, int]:
    """Convert tile coordinates to pixel coords (X-mirrored)."""
    px = int((max_x - x) * scale)
    py = int((y - 1) * scale)
    return px, py


def _draw_circle(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color: tuple[int, ...],
) -> None:
    """Draw a filled circle with black outline."""
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color, outline=(0, 0, 0))


def _draw_square(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, s: int, color: tuple[int, ...],
) -> None:
    """Draw a filled square with black outline."""
    half = s // 2
    draw.rectangle(
        [cx - half, cy - half, cx + half, cy + half],
        fill=color, outline=(0, 0, 0),
    )


def _draw_diamond(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, s: int, color: tuple[int, ...],
) -> None:
    """Draw a filled diamond with black outline."""
    draw.polygon(
        [(cx, cy - s), (cx + s, cy), (cx, cy + s), (cx - s, cy)],
        fill=color, outline=(0, 0, 0),
    )


def _draw_triangle_up(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, s: int, color: tuple[int, ...],
) -> None:
    """Draw an upward-pointing triangle with black outline."""
    draw.polygon(
        [(cx, cy - s), (cx + s, cy + s), (cx - s, cy + s)],
        fill=color, outline=(0, 0, 0),
    )


def _draw_triangle_down(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, s: int, color: tuple[int, ...],
) -> None:
    """Draw a downward-pointing triangle with black outline."""
    draw.polygon(
        [(cx, cy + s), (cx + s, cy - s), (cx - s, cy - s)],
        fill=color, outline=(0, 0, 0),
    )


def _get_font(size: int = 16) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a font at the given size, falling back to default bitmap font."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


_SHAPE_DRAWERS = {
    "circle": _draw_circle,
    "square": _draw_square,
    "diamond": _draw_diamond,
    "triangle_up": _draw_triangle_up,
    "triangle_down": _draw_triangle_down,
}

# Station transport type -> PIL shape name
_STATION_SHAPES: dict[str, str] = {
    "air": "triangle_up",
    "rail": "square",
    "water": "triangle_down",
    "road": "diamond",
}

# Station transport type -> color (RGB)
_STATION_COLORS: dict[str, tuple[int, ...]] = {
    "air": COLOR_AIR[1],
    "rail": COLOR_RAIL[1],
    "water": COLOR_SHIP[1],
    "road": COLOR_ROAD[1],
}


def _draw_infrastructure(
    draw: ImageDraw.ImageDraw,
    segments: list[InfraSegment],
    game_date: int,
    max_x: int,
    scale: int,
    line_width: int,
) -> None:
    """Draw rail and road infrastructure lines built up to game_date."""
    for seg in segments:
        if seg.game_date > game_date:
            break  # segments are sorted by game_date
        color = COLOR_RAIL_LINE_RGB if seg.infra_type == "rail" else COLOR_ROAD_LINE_RGB
        px1, py1 = _coord_to_pixel(seg.x1, seg.y1, max_x, scale)
        px2, py2 = _coord_to_pixel(seg.x2, seg.y2, max_x, scale)
        draw.line([(px1, py1), (px2, py2)], fill=color, width=line_width)


def _draw_markers(
    draw: ImageDraw.ImageDraw,
    snapshot_data: dict,
    max_x: int,
    scale: int,
    q: VideoQuality,
) -> None:
    """Draw all entity markers on the frame with transport-type colors."""
    # Towns (red circles)
    for town in snapshot_data.get("towns", []):
        if "x" in town and "y" in town:
            px, py = _coord_to_pixel(town["x"], town["y"], max_x, scale)
            _draw_circle(draw, px, py, q.marker_town, COLOR_TOWN[1])

    # Industries (orange diamonds)
    for ind in snapshot_data.get("industries", []):
        if "x" in ind and "y" in ind:
            px, py = _coord_to_pixel(ind["x"], ind["y"], max_x, scale)
            _draw_diamond(draw, px, py, q.marker_industry, COLOR_INDUSTRY[1])

    # Stations -- shape and color by transport type
    for st in snapshot_data.get("stations", []):
        if "x" not in st or "y" not in st:
            continue
        px, py = _coord_to_pixel(st["x"], st["y"], max_x, scale)
        stype = classify_station_type(st)
        shape = _STATION_SHAPES.get(stype, "diamond")
        color = _STATION_COLORS.get(stype, COLOR_ROAD[1])
        _SHAPE_DRAWERS[shape](draw, px, py, q.marker_station, color)

    # Vehicles -- colored circle by transport type
    for veh in snapshot_data.get("vehicles", []):
        if "x" not in veh or "y" not in veh:
            continue
        px, py = _coord_to_pixel(veh["x"], veh["y"], max_x, scale)
        color = VEHICLE_COLORS.get(veh.get("type", ""), COLOR_ROAD)[1]
        _draw_circle(draw, px, py, q.marker_vehicle, color)


def _draw_hud(
    draw: ImageDraw.ImageDraw,
    y_offset: int,
    width: int,
    game_date: int,
    balance: int,
    num_stations: int,
    num_vehicles: int,
    q: VideoQuality,
) -> None:
    """Draw a HUD bar with game stats and legend at bottom of frame."""
    draw.rectangle([0, y_offset, width, y_offset + q.hud_height], fill=COLOR_HUD_BG_RGB)

    font = _get_font(q.font_main)
    font_sm = _get_font(q.font_small)

    date_str = game_date_to_str(game_date)
    balance_str = f"${balance:,}" if balance else "$0"
    stats = (
        f"  {date_str}   |   Balance: {balance_str}"
        f"   |   Stations: {num_stations}   |   Vehicles: {num_vehicles}"
    )
    draw.text((10, y_offset + 6), stats, fill=COLOR_HUD_TEXT_RGB, font=font)

    # Legend row: transport types
    legend_y = y_offset + q.font_main + 16
    x_pos = 10
    marker_r = q.legend_marker
    char_width = max(7, q.font_small // 2 + 2)
    for label, color_pair, shape in LEGEND_ITEMS:
        rgb = color_pair[1]
        cy = legend_y + marker_r
        _SHAPE_DRAWERS[shape](draw, x_pos + marker_r, cy, marker_r, rgb)
        draw.text((x_pos + marker_r * 2 + 6, legend_y), label, fill=rgb, font=font_sm)
        x_pos += len(label) * char_width + marker_r * 2 + 20


def _render_frame(
    base_terrain: np.ndarray,
    snapshot_data: dict,
    game_date: int,
    max_x: int,
    scale: int,
    q: VideoQuality,
    infra_segments: list[InfraSegment],
) -> np.ndarray:
    """Render a single video frame: terrain + infrastructure + markers + HUD."""
    terrain_h, terrain_w = base_terrain.shape[:2]

    # Ensure even dimensions for libx264
    frame_h = terrain_h + q.hud_height
    if frame_h % 2:
        frame_h += 1
    frame_w = terrain_w
    if frame_w % 2:
        frame_w += 1

    frame = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)
    frame[:terrain_h, :terrain_w] = base_terrain

    img = Image.fromarray(frame)
    draw = ImageDraw.Draw(img)

    # Draw infrastructure lines (rail/road) under markers
    _draw_infrastructure(draw, infra_segments, game_date, max_x, scale, q.line_width)

    # Draw entity markers on top
    _draw_markers(draw, snapshot_data, max_x, scale, q)

    companies = snapshot_data.get("companies", [])
    balance = companies[0].get("money", 0) if companies else 0
    num_stations = len(snapshot_data.get("stations", []))
    num_vehicles = len(snapshot_data.get("vehicles", []))

    _draw_hud(draw, terrain_h, frame_w, game_date, balance, num_stations, num_vehicles, q)

    return np.array(img)


def _write_video_av(
    output_path: Path,
    frames_iter: object,
    width: int,
    height: int,
    fps: int,
    crf: int,
    preset: str,
) -> int:
    """Write frames to MP4 using pyav with explicit quality control.

    Returns number of frames written.
    """
    import av

    container = av.open(str(output_path), mode="w")
    stream = container.add_stream("libx264", rate=fps)
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": str(crf), "preset": preset}

    count = 0
    for frame_data in frames_iter:
        frame = av.VideoFrame.from_ndarray(frame_data, format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)
        count += 1

    # Flush encoder
    for packet in stream.encode():
        container.mux(packet)

    container.close()
    return count


def generate_video(
    session: SessionData,
    output_path: Path | None = None,
    fps: int = 4,
    quality: str = "high",
    max_frames: int = 0,
) -> Path:
    """Generate terrain-based video showing game progression.

    Renders tile terrain as background and overlays game objects from each
    snapshot, showing stations, vehicles, and infrastructure appearing over
    time. Falls back to screenshot timelapse if no tile data is available.

    Args:
        session: Loaded session data with tiles and snapshots.
        output_path: Where to write the MP4. Defaults to session reports dir.
        fps: Frames per second.
        quality: Quality preset: "low", "medium", or "high".
        max_frames: Maximum frames to render. 0 means use all snapshots.
            Snapshots are sampled evenly if there are more than this.

    Returns:
        Path to the generated MP4 file.
    """
    q = _QUALITY_PRESETS.get(quality, _QUALITY_PRESETS["high"])

    if output_path is None:
        reports_dir = session.session_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_path = reports_dir / f"game_progression_{session.session_id}.mp4"
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # Try terrain-based video
    result = _build_base_terrain(session.tiles, q.scale)
    if result is None or session.snapshots.is_empty():
        return _generate_screenshot_video(session.session_dir, output_path, fps)

    base_terrain, max_x, max_y = result

    # Extract infrastructure segments from actions (tile IDs use map_width = next power of 2)
    map_width = _next_power_of_2(max_x)
    infra_segments = _extract_infrastructure(session.actions, map_width)
    logger.info("Extracted %d infrastructure segments from actions", len(infra_segments))

    snapshots = session.snapshots.sort("game_date")
    total = len(snapshots)

    # Sample frames evenly if max_frames is set
    if max_frames > 0 and total > max_frames:
        indices = np.linspace(0, total - 1, max_frames, dtype=int).tolist()
        snapshots = snapshots[indices]

    num_frames = len(snapshots)
    terrain_h, terrain_w = base_terrain.shape[:2]
    frame_h = terrain_h + q.hud_height
    if frame_h % 2:
        frame_h += 1
    frame_w = terrain_w
    if frame_w % 2:
        frame_w += 1

    logger.info(
        "Generating terrain video: %d frames at %dfps, %dx%d (quality=%s, crf=%d)",
        num_frames, fps, frame_w, frame_h, quality, q.crf,
    )

    def frame_generator() -> np.ndarray:
        for idx, row in enumerate(snapshots.iter_rows(named=True)):
            snap_data = json.loads(row["snapshot_json"])
            frame = _render_frame(
                base_terrain, snap_data, int(row["game_date"]),
                max_x, q.scale, q, infra_segments,
            )
            if (idx + 1) % 50 == 0:
                logger.info("  Rendered %d/%d frames", idx + 1, num_frames)
            yield frame

    count = _write_video_av(
        output_path, frame_generator(), frame_w, frame_h, fps, q.crf, q.preset,
    )
    logger.info("Wrote terrain video to %s (%d frames)", output_path, count)
    return output_path


def _generate_screenshot_video(
    session_dir: Path,
    output_path: Path,
    fps: int,
) -> Path:
    """Fallback: create MP4 timelapse from session screenshot PNGs."""
    import imageio.v3 as iio

    screenshot_dir = session_dir / "screenshot"
    if not screenshot_dir.exists():
        msg = f"No screenshot directory and no tile data: {screenshot_dir}"
        raise FileNotFoundError(msg)

    frames = sorted(screenshot_dir.glob("*.png"))
    if not frames:
        msg = f"No PNG screenshots in {screenshot_dir}"
        raise FileNotFoundError(msg)

    logger.info(
        "Fallback: screenshot timelapse from %d frames at %d fps", len(frames), fps,
    )

    with iio.imopen(str(output_path), "w", plugin="pyav") as writer:
        writer.init_video_stream("libx264", fps=fps)
        for frame_path in frames:
            img = iio.imread(str(frame_path))
            writer.write_frame(img)

    logger.info("Wrote screenshot video to %s", output_path)
    return output_path
