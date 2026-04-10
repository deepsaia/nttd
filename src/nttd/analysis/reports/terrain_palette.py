"""Shared terrain palette and entity style constants.

Single source of truth for colors, colorscales, and marker styles
used by both tile_map.py (Plotly static image) and video.py (PIL
video frames).
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Terrain colorscale for Plotly heatmaps
#
# Water occupies [0.0, 0.1) as a uniform band; land occupies [0.1, 1.0].
# Pair this with compute_water_value() which sets water tile z-values so
# they always map to exactly the 0.0-0.1 range regardless of height range.
# ---------------------------------------------------------------------------
TERRAIN_COLORSCALE: list[list] = [
    [0.0, "#1a5276"],    # deep water (dark navy blue)
    [0.05, "#2471a3"],   # mid-depth water (ocean blue)
    [0.099, "#5dade2"],  # shallow water / coast (light blue)
    [0.1, "#f9e79f"],    # beach / coast (sand yellow)
    [0.3, "#27ae60"],    # low grassland (bright green)
    [0.5, "#1e8449"],    # mid-altitude land (forest green)
    [0.7, "#784212"],    # hills / mountains (brown)
    [1.0, "#f5f5f5"],    # snow peaks (near white)
]

# Fraction of the colorscale reserved for the water band
_WATER_BAND = 0.1


def _compute_water_range(
    land_min: float, land_max: float,
) -> tuple[float, float]:
    """Compute the z-value range for water tiles in the terrain heatmap.

    Returns (water_low, water_high) such that the water band occupies
    exactly the first 10% of the Plotly colorscale.  Water heights are
    then linearly mapped into this range to show depth variation
    (deep = dark blue, shallow = light blue).
    """
    # water_high is just below land_min so the beach transition is sharp
    water_high = land_min - 0.01
    # water_low is computed so [water_low, land_max] spans the full colorscale
    # with [water_low, water_high] covering exactly _WATER_BAND of it
    total_range = (land_max - water_high) / (1 - _WATER_BAND)
    water_low = land_max - total_range
    return water_low, water_high


def prepare_terrain_grid(
    tiles_df: object,
) -> tuple[np.ndarray, int, int] | None:
    """Build a 2D terrain grid from tiles DataFrame with water separation.

    Water tile heights are mapped into a separate band below land so
    the colorscale shows depth variation (deep=dark, shallow=light).
    Works correctly for any map size and height range.

    Returns (terrain_z, max_x, max_y) or None if tiles are empty.
    """
    if hasattr(tiles_df, "empty") and tiles_df.empty:
        return None

    max_x = int(tiles_df["x"].max())
    max_y = int(tiles_df["y"].max())

    height_grid = np.full((max_y, max_x), np.nan)
    water_mask = np.zeros((max_y, max_x), dtype=bool)

    xs = tiles_df["x"].values.astype(int) - 1
    ys = tiles_df["y"].values.astype(int) - 1
    heights = tiles_df["height"].values.astype(float)
    flags = tiles_df["flags"].values.astype(int)

    valid = (xs >= 0) & (xs < max_x) & (ys >= 0) & (ys < max_y)
    height_grid[ys[valid], xs[valid]] = heights[valid]
    water_mask[ys[valid], xs[valid]] = (flags[valid] & 1).astype(bool)

    # Compute water band range from the land height extremes
    land_heights = height_grid[~water_mask & ~np.isnan(height_grid)]
    if len(land_heights) == 0:
        return None
    land_min = float(np.min(land_heights))
    land_max = float(np.max(land_heights))
    water_low, water_high = _compute_water_range(land_min, land_max)

    # Map water heights proportionally into the water band
    # Lower water heights -> deeper (darker), higher -> shallower (lighter)
    terrain = height_grid.copy()
    water_heights = terrain[water_mask]
    w_min = np.nanmin(water_heights) if len(water_heights) > 0 else 0.0
    w_max = np.nanmax(water_heights) if len(water_heights) > 0 else 0.0
    w_range = w_max - w_min
    if w_range > 0:
        terrain[water_mask] = water_low + (water_heights - w_min) / w_range * (water_high - water_low)
    else:
        terrain[water_mask] = (water_low + water_high) / 2
    terrain = np.nan_to_num(terrain, nan=water_low)

    return terrain, max_x, max_y


# ---------------------------------------------------------------------------
# Entity colors -- (plotly_hex, pil_rgb) pairs
# ---------------------------------------------------------------------------
COLOR_TOWN = ("#ff3c3c", (255, 60, 60))
COLOR_INDUSTRY = ("#ffa500", (255, 165, 0))
COLOR_RAIL = ("#4488ff", (68, 136, 255))
COLOR_ROAD = ("#64c864", (100, 200, 100))
COLOR_AIR = ("#c864ff", (200, 100, 255))
COLOR_SHIP = ("#44c8c8", (68, 200, 200))

# Infrastructure line colors (dimmer shades, PIL only)
COLOR_RAIL_LINE_RGB = (50, 100, 200)
COLOR_ROAD_LINE_RGB = (80, 160, 80)

# HUD colors (PIL only)
COLOR_HUD_BG_RGB = (20, 20, 30)
COLOR_HUD_TEXT_RGB = (220, 220, 220)

# Vehicle type -> color mapping
VEHICLE_COLORS: dict[str, tuple[str, tuple[int, ...]]] = {
    "train": COLOR_RAIL,
    "road": COLOR_ROAD,
    "aircraft": COLOR_AIR,
    "ship": COLOR_SHIP,
}

# Plotly marker symbol per station transport type
STATION_PLOTLY_SYMBOLS: dict[str, str] = {
    "rail": "square",
    "road": "diamond",
    "air": "triangle-up",
    "water": "triangle-down",
}

# Legend items: (label, color_pair, pil_shape_name)
LEGEND_ITEMS: list[tuple[str, tuple[str, tuple[int, ...]], str]] = [
    ("Towns", COLOR_TOWN, "circle"),
    ("Industries", COLOR_INDUSTRY, "diamond"),
    ("Rail", COLOR_RAIL, "square"),
    ("Road", COLOR_ROAD, "diamond"),
    ("Air", COLOR_AIR, "triangle_up"),
    ("Water", COLOR_SHIP, "triangle_down"),
]


def classify_station_type(station: dict) -> str:
    """Determine the primary transport type of a station."""
    if station.get("has_airport"):
        return "air"
    if station.get("has_rail"):
        return "rail"
    if station.get("has_dock"):
        return "water"
    if station.get("has_truck") or station.get("has_bus"):
        return "road"
    return "road"
