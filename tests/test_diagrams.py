"""The generated diagrams have to survive being rendered.

A label that runs past its viewBox is invisible in the SVG source and only shows up
when somebody opens the file. Three of these shipped that way, including one in
architecture.svg that an earlier check missed because it compared raw ``x`` values and
ignored ``text-anchor``: a centred title looked wrong while a genuinely clipped
left-anchored label looked fine.

These diagrams are also embedded in a README that GitHub renders in whichever theme
the reader chose, so a hardcoded light background is unreadable for half the audience.
"""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_IMAGES = _ROOT / "docs" / "images"
_GENERATOR = _ROOT / "scripts" / "generate_diagrams.py"

_TEXT = re.compile(r"<text([^>]*)>([^<]*)</text>")
_MARGIN = 6.0


def _svg_files() -> list[Path]:
    return sorted(_IMAGES.glob("*.svg"))


def _viewbox(text: str) -> tuple[int, int]:
    match = re.search(r'viewBox="0 0 (\d+) (\d+)"', text)
    assert match, "every diagram needs a viewBox"
    return int(match.group(1)), int(match.group(2))


def _extent(attrs: str, body: str) -> tuple[float, float]:
    """Return the (left, right) span a label occupies, honouring text-anchor."""
    from scripts.generate_diagrams import text_width

    x = float(re.search(r'\bx="([\d.]+)"', attrs).group(1))
    size = re.search(r'font-size="(\d+)"', attrs)
    width = text_width(body, int(size.group(1)) if size else 12)

    if 'text-anchor="middle"' in attrs:
        return x - width / 2, x + width / 2
    if 'text-anchor="end"' in attrs:
        return x - width, x
    return x, x + width


@pytest.mark.parametrize("path", _svg_files(), ids=lambda p: p.name)
def test_the_diagram_is_valid_xml(path: Path) -> None:
    # stdlib ElementTree rather than defusedxml: the only input is a file this repo's
    # own generator just wrote, so there is no untrusted document and no entity
    # expansion to defend against. Taking a dependency for a test-only parse would
    # also cut against installing everything in one uv sync.
    ET.fromstring(path.read_text())


@pytest.mark.parametrize("path", _svg_files(), ids=lambda p: p.name)
def test_every_label_fits_inside_the_viewbox(path: Path) -> None:
    text = path.read_text()
    width, _ = _viewbox(text)

    clipped = []
    for match in _TEXT.finditer(text):
        body = match.group(2).strip()
        if not body:
            continue
        left, right = _extent(match.group(1), body)
        if left < _MARGIN or right > width - _MARGIN:
            clipped.append(f"[{left:.0f}..{right:.0f}] of {width}: {body!r}")

    assert not clipped, f"{path.name} clips {len(clipped)} label(s):\n  " + "\n  ".join(clipped)


@pytest.mark.parametrize("path", _svg_files(), ids=lambda p: p.name)
def test_every_shape_fits_inside_the_viewbox(path: Path) -> None:
    text = path.read_text()
    width, height = _viewbox(text)

    for match in re.finditer(
        r'<rect[^>]*\bx="([\d.]+)"[^>]*\by="([\d.]+)"[^>]*'
        r'width="([\d.]+)"[^>]*height="([\d.]+)"', text,
    ):
        x, y, w, h = (float(g) for g in match.groups())
        assert x + w <= width, f"{path.name}: a rect ends at {x + w} past width {width}"
        assert y + h <= height, f"{path.name}: a rect ends at {y + h} past height {height}"


@pytest.mark.parametrize("path", _svg_files(), ids=lambda p: p.name)
def test_the_diagram_reads_in_dark_mode(path: Path) -> None:
    assert "prefers-color-scheme: dark" in path.read_text()


def test_the_committed_diagrams_match_the_generator() -> None:
    """Otherwise a diagram drifts from the code that claims to produce it."""
    before = {path: path.read_text() for path in _svg_files()}
    subprocess.run(
        [sys.executable, str(_GENERATOR)], cwd=_ROOT, check=True, capture_output=True,
    )
    stale = [path.name for path, text in before.items() if path.read_text() != text]
    assert not stale, (
        "these diagrams differ from what the generator produces: "
        f"{stale}. Run: uv run python scripts/generate_diagrams.py"
    )


def test_the_worlds_diagram_is_built_from_the_live_profile() -> None:
    """A hardcoded matrix would keep claiming 25 maps after the profile narrowed."""
    from nttd.config.benchmark_profile import ALLOWED_RANGES

    text = (_IMAGES / "scoreable_worlds.svg").read_text()
    for size in ALLOWED_RANGES["size"]:
        assert f">{size}<" in text, f"size {size} is missing from the diagram"
    for terrain in ALLOWED_RANGES["terrain_type"]:
        assert f">{terrain}<" in text, f"terrain {terrain} is missing from the diagram"

    count = len(ALLOWED_RANGES["size"]) * len(ALLOWED_RANGES["terrain_type"])
    assert f"= {count} maps" in text
