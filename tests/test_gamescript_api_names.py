"""Every GameScript API call names a function that exists.

Squirrel resolves a member at call time, so a name that is wrong is not a syntax error and
not caught by anything until an agent asks the question. Worse, it takes the whole reply
with it: one bad call inside get_vehicle_info raised "the index 'HasSharedOrders' does not
exist" and made that query return nothing for every vehicle, for as long as it was there.

That cost real time. A wagon bought with a valid id looked invalid, because the only way to
check an id was the query that was broken, so the id was blamed. See issue #47.

This checks the calls against the running OpenTTD binary, which is the only authority on
what its API offers. Skipped when the binary cannot be found, since the check is worthless
without it rather than merely inconvenient.

Worth being clear about its limit. The binary's symbols say whether a NAME exists anywhere,
not which class carries it. HasSharedOrders is in there, as a method of something else, so
this check alone would not have caught it: the named test below does that, and a call on
the wrong class remains the gap. Catching those properly needs the API reference, or a live
probe of every read-only query, which the live suite is the place for.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

GAMESCRIPT = Path(__file__).resolve().parents[1] / "ottd_config/game/nttd-gs/main.nut"

# Calls whose names are not method symbols in the binary, and why that is expected.
#
# Constructors and enum members are not registered the way methods are, so their absence
# from the symbol table says nothing about whether they exist.
_NOT_METHODS = re.compile(
    r"^GS\w+\.(?:"
    r"[A-Z][A-Z0-9_]+"          # enum members, e.g. GSRail.RAILTRACK_NE_SW
    r")$",
)


def _calls() -> set[str]:
    """Every GS API call the script makes, as Class.Method.

    Comments are stripped first. They discuss API names, including the wrong one this
    file exists because of, and counting those as calls makes the check report its own
    documentation.
    """
    lines = []
    for line in GAMESCRIPT.read_text().split("\n"):
        head, _, _ = line.partition("//")
        lines.append(head)
    source = "\n".join(lines)
    found = set(re.findall(r"\b(GS[A-Za-z]+)\.([A-Za-z]\w*)", source))
    return {f"{cls}.{method}" for cls, method in found}


@pytest.fixture(scope="module")
def binary_symbols() -> set[str]:
    # The same environment variable the server reads, with the same default. Resolved here
    # rather than imported because nttd has no single place that answers this yet, which is
    # its own open item.
    binary = os.environ.get(
        "NTTD_OPENTTD_BINARY", "/Applications/OpenTTD.app/Contents/MacOS/openttd",
    )
    if not Path(binary).exists():
        pytest.skip("OpenTTD binary not found, so its API cannot be consulted")
    out = subprocess.run(
        ["strings", binary], capture_output=True, text=True, check=False,
    )
    return set(out.stdout.split("\n"))


def test_every_api_method_the_script_calls_exists_in_the_binary(
    binary_symbols: set[str],
) -> None:
    """The check that would have caught HasSharedOrders before an agent did."""
    missing = []
    for call in sorted(_calls()):
        if _NOT_METHODS.match(call):
            continue
        method = call.split(".", 1)[1]
        if method not in binary_symbols:
            missing.append(call)
    assert missing == [], (
        "these calls name functions absent from the OpenTTD binary, and each one will "
        f"take its whole reply with it when reached: {missing}"
    )


def test_the_call_that_broke_get_vehicle_info_is_gone() -> None:
    """Named rather than left to the general check, because this one has a history.

    Against the parsed calls rather than the raw text: the name appears in a comment
    explaining what went wrong, and that comment is worth keeping.
    """
    assert "GSOrder.HasSharedOrders" not in _calls()
