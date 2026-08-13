"""The terrain raster.

Encoded with zlib rather than Pillow, so the bytes are this project's responsibility. A
malformed PNG fails in the browser and nowhere else, which is the worst place to find out,
so the structure is asserted here: signature, chunk order, and the declared size matching
the tile grid.
"""

from __future__ import annotations

import struct
import zlib

import polars as pl

from nttd.monitor.terrain_png import FLAG_COAST, FLAG_WATER, TerrainPng

_LAND = 4  # buildable


def _tiles(rows: list[tuple[int, int, int, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "x": [r[0] for r in rows],
            "y": [r[1] for r in rows],
            "height": [r[2] for r in rows],
            "slope": [0] * len(rows),
            "flags": [r[3] for r in rows],
        },
        schema={"x": pl.Int16, "y": pl.Int16, "height": pl.Int8,
                "slope": pl.Int8, "flags": pl.Int8},
    )


def _grid(width: int, height: int, flags: int = _LAND) -> pl.DataFrame:
    return _tiles([
        (x, y, (x + y) % 5, flags)
        for y in range(1, height + 1)
        for x in range(1, width + 1)
    ])


def _chunks(png: bytes) -> list[str]:
    """The chunk types in order, parsed the way a decoder would."""
    out: list[str] = []
    offset = 8
    while offset < len(png):
        (length,) = struct.unpack(">I", png[offset:offset + 4])
        kind = png[offset + 4:offset + 8].decode("ascii")
        out.append(kind)
        offset += 12 + length
    return out


def _pixels(png: bytes, width: int, height: int) -> list[tuple[int, int, int]]:
    """Decode the image back to RGB triples, without a decoding library."""
    data = b""
    offset = 8
    while offset < len(png):
        (length,) = struct.unpack(">I", png[offset:offset + 4])
        kind = png[offset + 4:offset + 8]
        if kind == b"IDAT":
            data += png[offset + 8:offset + 8 + length]
        offset += 12 + length
    raw = zlib.decompress(data)
    stride = width * 3 + 1
    assert len(raw) == stride * height
    out: list[tuple[int, int, int]] = []
    for row in range(height):
        start = row * stride
        assert raw[start] == 0, "filter type must be none"
        for column in range(width):
            base = start + 1 + column * 3
            out.append((raw[base], raw[base + 1], raw[base + 2]))
    return out


# ----------------------------------------------------------------------


def test_a_session_with_no_terrain_renders_nothing() -> None:
    assert TerrainPng(pl.DataFrame()).encode() is None
    assert TerrainPng(None).encode() is None


def test_a_frame_missing_the_tile_columns_is_declined() -> None:
    """An older layout must not produce a garbled image."""
    assert TerrainPng(pl.DataFrame({"x": [1], "y": [1]})).encode() is None


def test_the_image_is_a_structurally_valid_png() -> None:
    png, _x, _y, width, height = TerrainPng(_grid(8, 6)).encode()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert _chunks(png) == ["IHDR", "IDAT", "IEND"]
    declared = struct.unpack(">II", png[16:24])
    assert declared == (width, height) == (8, 6)


def test_every_chunk_carries_a_correct_crc() -> None:
    """A wrong CRC is exactly the failure that only shows up in the browser."""
    png, *_ = TerrainPng(_grid(5, 5)).encode()
    offset = 8
    while offset < len(png):
        (length,) = struct.unpack(">I", png[offset:offset + 4])
        body = png[offset + 4:offset + 8 + length]
        (stored,) = struct.unpack(">I", png[offset + 8 + length:offset + 12 + length])
        assert stored == zlib.crc32(body)
        offset += 12 + length


def test_the_placement_matches_where_the_tiles_actually_are() -> None:
    """Tiles run from 1, so an image drawn at the origin sits a tile off the stations."""
    _png, x0, y0, width, height = TerrainPng(_grid(10, 7)).encode()
    assert (x0, y0) == (1, 1)
    assert (width, height) == (10, 7)


def test_water_and_land_are_different_colours() -> None:
    tiles = _tiles([(1, 1, 0, FLAG_WATER), (2, 1, 3, _LAND)])
    png, _x, _y, width, height = TerrainPng(tiles).encode()
    water, land = _pixels(png, width, height)
    assert water != land
    # Water sits in the blue band of the shared palette: more blue than red.
    assert water[2] > water[0]


def test_coast_is_a_different_shade_from_open_water() -> None:
    tiles = _tiles([(1, 1, 0, FLAG_WATER), (2, 1, 0, FLAG_WATER | FLAG_COAST)])
    png, _x, _y, width, height = TerrainPng(tiles).encode()
    open_water, coast = _pixels(png, width, height)
    assert open_water != coast


def test_a_gap_in_the_scan_is_filled_rather_than_left_undefined() -> None:
    """A partial grid should read as an incomplete map, not as a hole."""
    tiles = _tiles([(1, 1, 2, _LAND), (3, 1, 2, _LAND)])
    png, _x, _y, width, height = TerrainPng(tiles).encode()
    pixels = _pixels(png, width, height)
    assert len(pixels) == 3
    assert all(sum(pixel) > 0 for pixel in pixels)


def test_the_newest_reading_of_a_tile_wins() -> None:
    """Terrain deltas append, so a changed tile appears twice."""
    tiles = _tiles([(1, 1, 0, FLAG_WATER), (1, 1, 4, _LAND)])
    png, _x, _y, width, height = TerrainPng(tiles).encode()
    (pixel,) = _pixels(png, width, height)
    water_only = _pixels(*_encoded(_tiles([(1, 1, 0, FLAG_WATER)])))
    assert pixel != water_only[0]


def test_a_flat_map_does_not_divide_by_zero() -> None:
    tiles = _tiles([(x, 1, 3, _LAND) for x in range(1, 5)])
    png, _x, _y, width, height = TerrainPng(tiles).encode()
    pixels = _pixels(png, width, height)
    assert len(set(pixels)) == 1


def test_terrain_compresses_far_smaller_than_the_tile_count() -> None:
    """The reason this is a raster and not SVG rectangles."""
    png, *_ = TerrainPng(_grid(256, 256)).encode()
    assert len(png) < 256 * 256 * 3 / 10


def _encoded(tiles: pl.DataFrame) -> tuple[bytes, int, int]:
    png, _x, _y, width, height = TerrainPng(tiles).encode()
    return png, width, height
