"""Sanitises game-sourced text before it reaches an agent's observation.

Company names, vehicle names, station names, and map signs are all writable by a
contestant (``rename_company``, ``rename_vehicle``, ``build_sign``). The
GameScript passes those strings through unchanged, and they land verbatim in every
other agent's observation, which becomes part of its prompt. That is a cheap and
undetectable way to try to steer a rival, and it costs nothing to close.

Two defences, because neither is sufficient alone:

  Strip the characters that let text escape its field. Newlines and control codes
  are what turn a company name into what looks like a new instruction or a new
  section of the prompt.

  Wrap what remains so its position in the prompt is unambiguous. A caller that
  renders game text into a prompt should use ``as_data_block`` and state that the
  contents are data.

This does not make injection impossible -- a name can still read as an
instruction. It removes the structural tricks and makes the remainder visible.
"""

from __future__ import annotations

import re

# OpenTTD's own company name limit is around 30 characters, and station and sign
# names are similar. 64 leaves room for longer generated names while stopping a
# contestant from spending an unbounded slice of a rival's context window.
MAX_TEXT_LENGTH = 64

_TRUNCATION_MARKER = "..."

# Anything that could end a line or a field: C0/C1 control codes, the Unicode line
# and paragraph separators, and the bidirectional overrides that let text render in
# an order other than the one it is stored in.
_CONTROL_CHARS = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f  ‪-‮⁦-⁩]"
)

# Tabs and newlines get a space rather than deletion, so words do not run together.
_WHITESPACE = re.compile(r"[\t\n\r]+")

# Collapse runs of spaces left behind by the substitutions above.
_MULTI_SPACE = re.compile(r" {2,}")


def sanitise(text: object, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Return ``text`` safe to place in an observation field.

    Removes control characters and bidirectional overrides, folds newlines and tabs
    to spaces, collapses repeated spaces, and truncates. Non-string input is
    coerced, so a caller need not check first.

    Args:
        text: The game-sourced value. ``None`` becomes an empty string.
        max_length: Maximum length of the result, including the truncation marker.
    """
    if text is None:
        return ""

    cleaned = _WHITESPACE.sub(" ", str(text))
    cleaned = _CONTROL_CHARS.sub("", cleaned)
    cleaned = _MULTI_SPACE.sub(" ", cleaned).strip()

    if len(cleaned) > max_length:
        keep = max(0, max_length - len(_TRUNCATION_MARKER))
        cleaned = cleaned[:keep].rstrip() + _TRUNCATION_MARKER
    return cleaned


def sanitise_mapping(
    data: dict[str, object], fields: tuple[str, ...], max_length: int = MAX_TEXT_LENGTH,
) -> dict[str, object]:
    """Return a copy of ``data`` with the named fields sanitised.

    Convenience for the common case of a dict built from game state where only some
    keys hold contestant-writable text.
    """
    result = dict(data)
    for field in fields:
        if field in result:
            result[field] = sanitise(result[field], max_length=max_length)
    return result


# Keys whose values are contestant-writable, or derived from names that are.
# Applied recursively, so a new observation section is covered without being
# individually remembered.
UNTRUSTED_KEYS: frozenset[str] = frozenset({
    "name",
    "company_name",
    "station_name",
    "town_name",
    "vehicle_name",
    "nearest_town",
    "src_name",
    "dst_name",
    "text",
    "sign_text",
    "manager",
})


def sanitise_observation(value: object, max_length: int = MAX_TEXT_LENGTH) -> object:
    """Recursively sanitise every untrusted-key string in an observation.

    Applied once at the boundary where an observation is handed to an agent, rather
    than at each of the many places a name is copied out of game state. A field
    added later is covered automatically as long as it uses one of
    ``UNTRUSTED_KEYS``.
    """
    if isinstance(value, dict):
        return {
            key: (
                sanitise(item, max_length=max_length)
                if key in UNTRUSTED_KEYS and isinstance(item, str)
                else sanitise_observation(item, max_length=max_length)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitise_observation(item, max_length=max_length) for item in value]
    return value


def as_data_block(label: str, text: str) -> str:
    """Wrap game text so its boundaries are unambiguous in a prompt.

    Use when rendering game-sourced text into an instruction, and state alongside it
    that the contents are data rather than instructions. The text is sanitised
    first, so the delimiters cannot be broken by the content.
    """
    return f"<{label}>{sanitise(text)}</{label}>"
