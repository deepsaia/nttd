"""nttd reports one version, and it is the installed one.

There were three numbers and no two agreed: api/app.py said "0.2.0", pyproject said 0.1.0, and
the newest release was 0.0.2. The one an agent reads, from /openapi.json, was the furthest from
the truth, and a recorded run could be attributed to a version that was never released.

pyproject's copy is already gone, since the version is derived from the release tag by
hatch-vcs. This covers the other half: the schema now reports what is installed rather than a
string somebody typed.
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

from nttd.api.app import app
from nttd.version import UNKNOWN, version

_APP_SOURCE = Path(__file__).resolve().parents[1] / "src" / "nttd" / "api" / "app.py"


def test_the_openapi_schema_reports_the_installed_version() -> None:
    assert app.openapi()["info"]["version"] == metadata.version("nttd")


def test_the_reported_version_is_not_a_placeholder() -> None:
    """A checkout that was never installed reports "unknown", which is honest. In the
    environment the tests run in, nttd IS installed, so an unknown here means the metadata
    lookup broke rather than that the answer is genuinely unavailable.
    """
    assert version() != UNKNOWN
    assert version() == metadata.version("nttd")


def test_no_hardcoded_version_string_is_left_in_the_app() -> None:
    """The specific mistake, rather than the general property: a literal version passed to
    FastAPI looks perfectly correct until someone compares it against a release.
    """
    text = _APP_SOURCE.read_text()
    assert "version=version()" in text
    assert 'version="0.2.0"' not in text
