"""The tab icon, and the route that answers for it.

Worth a test for a reason that is not the icon. The favicon handler was added in one edit and
the `assets` import it needs in the next, and a monitor started between the two answered
`/favicon.ico` by raising NameError inside the request thread. A browser shows that as a blank
tab and curl shows it as an empty reply, so nothing says what went wrong. These assertions
would have failed instead.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree

from nttd.monitor import assets, page, request_handler


class _Recorder:
    """Just enough of BaseHTTPRequestHandler to see what a responder wrote."""

    def __init__(self) -> None:
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self.body = b""

    def send_response(self, code: int) -> None:
        self.status = code

    def send_header(self, key: str, value: str) -> None:
        self.headers[key] = value

    def end_headers(self) -> None:
        pass

    @property
    def wfile(self) -> "_Recorder":
        return self

    def write(self, data: bytes) -> None:
        self.body += data


def _serve() -> _Recorder:
    handler = request_handler.MonitorHandler.__new__(request_handler.MonitorHandler)
    recorder = _Recorder()
    handler.send_response = recorder.send_response
    handler.send_header = recorder.send_header
    handler.end_headers = recorder.end_headers
    handler.wfile = recorder
    handler._serve_favicon()
    return recorder


def test_the_favicon_route_answers_with_an_svg() -> None:
    """The defect this exists for: it raised NameError and answered nothing at all."""
    served = _serve()
    assert served.status == 200
    assert served.headers["Content-Type"] == "image/svg+xml"
    assert served.body == assets.FAVICON_SVG.encode("utf-8")
    assert int(served.headers["Content-Length"]) == len(served.body)


def test_both_the_svg_and_the_ico_path_are_routed() -> None:
    """A browser asks for /favicon.ico whether or not it was told to.

    Answering only the path the page names leaves the other one falling through to the 404
    branch, which is a blank tab for anything that does not read the link tag. Driven through
    do_GET rather than read out of its source, so it is the routing being asserted.
    """
    for path in (request_handler.FAVICON_PATH, "/favicon.ico"):
        handler = request_handler.MonitorHandler.__new__(request_handler.MonitorHandler)
        handler.path = path
        reached: list[str] = []
        handler._serve_favicon = lambda: reached.append("yes")
        handler.do_GET()
        assert reached == ["yes"], f"{path} did not reach the favicon responder"


def test_the_page_asks_for_it() -> None:
    """Without the link tag a browser only ever tries /favicon.ico."""
    assert 'rel="icon"' in page.shell("<div></div>")
    assert request_handler.FAVICON_PATH in page.shell("<div></div>")


def test_the_icon_is_valid_svg_and_small_enough_to_inline() -> None:
    """It is inlined as a Python string, so it is read by people as well as browsers."""
    root = ElementTree.fromstring(assets.FAVICON_SVG)
    assert root.tag.endswith("svg")
    assert root.get("viewBox") == "0 0 32 32"
    assert len(assets.FAVICON_SVG) < 2048


def test_the_icon_carries_its_own_background() -> None:
    """A transparent glyph disappears into whichever tab bar it lands on.

    The dark rounded square is what lets one icon read on a light theme and a dark one
    without knowing which it is on.
    """
    root = ElementTree.fromstring(assets.FAVICON_SVG)
    rect = root.find("{http://www.w3.org/2000/svg}rect")
    assert rect is not None, "no background rect"
    assert rect.get("fill"), "the background rect is not filled"
