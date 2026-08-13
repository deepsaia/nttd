"""The map's terrain as a PNG, encoded here rather than by a library.

The monitor's map needs a real top-down view, and terrain is a raster: one pixel per tile.
A 256 square map is 65,536 tiles, so drawing it as SVG rectangles would be megabytes of
markup for a picture the browser can decode from a few kilobytes.

Encoded with ``zlib`` and ``struct`` from the standard library. Pillow would do this too
and ``analysis.reports.video`` already imports it, but Pillow is not declared in
``pyproject.toml``, so it is present only as somebody else's transitive dependency. Putting
an undeclared import in a live request path is how a dashboard breaks on a machine where
the dependency tree resolved differently. A PNG writer is thirty lines and the terrain is
smooth, so it compresses hard.

The colours are the stops from ``terrain_palette``, so this view, the tile_map report and
the video all agree about what shallow water looks like.
"""

from __future__ import annotations

import logging
import struct
import zlib
from typing import Any

from nttd.analysis.reports.terrain_palette import TERRAIN_COLORSCALE

logger = logging.getLogger(__name__)

# Tile flags, as the GameScript sets them.
FLAG_WATER = 1
FLAG_COAST = 2

# Where water sits on the colourscale. The palette reserves the first tenth for it, so
# these are read from that band rather than invented: open water mid band, coast at its
# top edge where the beach transition is.
_OPEN_WATER = 0.04
_COAST = 0.099
_LAND_FLOOR = 0.1


class TerrainPng:
    """One session's terrain, as an image the browser can draw in one go."""

    def __init__(self, tiles: Any) -> None:
        self._tiles = tiles
        self._stops = _parse_stops()

    def encode(self) -> tuple[bytes, int, int, int, int] | None:
        """The PNG and where it sits on the map.

        Returns ``(png, x0, y0, width, height)`` in tile coordinates, or None when the
        session recorded no terrain. The offset matters: tiles run from 1 to the map size
        less two, so an image drawn at the origin would sit a tile off from the stations
        plotted over it.
        """
        rows = self._rows()
        if not rows:
            return None
        xs = [row[0] for row in rows]
        x0, x1 = min(xs), max(xs)
        ys = sorted({row[1] for row in rows})
        y0, y1 = ys[0], ys[-1]
        width = x1 - x0 + 1
        height = y1 - y0 + 1
        if width <= 0 or height <= 0:
            return None

        heights = [row[2] for row in rows if not row[4] & FLAG_WATER]
        low = min(heights) if heights else 0
        high = max(heights) if heights else 1

        # Any tile the scan missed stays the deep water colour rather than transparent, so
        # a partial grid reads as an incomplete map instead of a hole in the land.
        blank = self._colour(_OPEN_WATER)
        canvas = [bytearray(blank * width) for _ in range(height)]
        for x, y, tile_height, _slope, flags in rows:
            offset = (x - x0) * 3
            canvas[y - y0][offset:offset + 3] = self._pixel(tile_height, flags, low, high)

        return _png(canvas, width, height), x0, y0, width, height

    # ------------------------------------------------------------------

    def _rows(self) -> list[tuple[int, int, int, int, int]]:
        """The newest reading per tile.

        Terrain deltas are appended after a change, so a tile can appear more than once
        and the last row is the current one.
        """
        frame = self._tiles
        if frame is None or getattr(frame, "is_empty", None) is None or frame.is_empty():
            return []
        needed = ("x", "y", "height", "slope", "flags")
        if any(column not in frame.columns for column in needed):
            return []
        latest: dict[tuple[int, int], tuple[int, int, int, int, int]] = {}
        for record in frame.select(needed).iter_rows():
            x, y, height, slope, flags = record
            latest[(int(x), int(y))] = (
                int(x), int(y), int(height), int(slope), int(flags),
            )
        return list(latest.values())

    def _pixel(self, height: int, flags: int, low: int, high: int) -> bytes:
        if flags & FLAG_WATER:
            return self._colour(_COAST if flags & FLAG_COAST else _OPEN_WATER)
        span = high - low
        share = 0.0 if span <= 0 else (height - low) / span
        return self._colour(_LAND_FLOOR + share * (1.0 - _LAND_FLOOR))

    def _colour(self, position: float) -> bytes:
        """The palette colour at a position, interpolated between its stops."""
        stops = self._stops
        if position <= stops[0][0]:
            return bytes(stops[0][1])
        if position >= stops[-1][0]:
            return bytes(stops[-1][1])
        for index in range(1, len(stops)):
            upper_at, upper = stops[index]
            if position <= upper_at:
                lower_at, lower = stops[index - 1]
                span = upper_at - lower_at
                share = 0.0 if span <= 0 else (position - lower_at) / span
                return bytes(
                    round(lower[channel] + share * (upper[channel] - lower[channel]))
                    for channel in range(3)
                )
        return bytes(stops[-1][1])


def _parse_stops() -> list[tuple[float, tuple[int, int, int]]]:
    """The shared colourscale as positions and RGB triples."""
    stops: list[tuple[float, tuple[int, int, int]]] = []
    for position, colour in TERRAIN_COLORSCALE:
        text = colour.lstrip("#")
        stops.append((
            float(position),
            (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)),
        ))
    stops.sort(key=lambda stop: stop[0])
    return stops


def _png(canvas: list[bytearray], width: int, height: int) -> bytes:
    """An 8 bit RGB PNG. No filtering, because zlib handles smooth terrain well."""
    raw = bytearray()
    for row in canvas:
        raw.append(0)
        raw.extend(row)
    return b"".join([
        b"\x89PNG\r\n\x1a\n",
        _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
        _chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
        _chunk(b"IEND", b""),
    ])


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
