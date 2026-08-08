"""Validating what arrives from the opponent.

Everything crossing the wire comes from an agent we do not control, do not
trust, and cannot debug. The rule is simple and absolute: **never trust an
unverified move**, and never let hostile input become an unhandled exception.

An unhandled exception here is not merely untidy. A crash mid-turn is a
technical loss scoring **zero for both sides**, so a peer that can be crashed
by a malformed payload hands its opponent a way to void any match it is
losing. Every failure must therefore be a structured refusal.

Validation is deliberately paranoid about types rather than trusting a JSON
decoder: ``True`` is an ``int`` in Python, and a payload of ``{"row": true}``
would otherwise index row 1.
"""

import unicodedata
from typing import Any

from ..domain.hints import FUTURE_ACTION, NUMERIC, policy_text
from .validation_primitives import (
    MAX_STRING,
    SHA256_HEX_CHARS,
    InvalidPayloadError,
    reject_unknown_fields,
    require_choice,
    require_digest,
    require_int,
    require_mapping,
    require_str,
)
from .validation_shapes import MAX_SCENT_CELLS, optional_cell, optional_scent

__all__ = [
    "MAX_SCENT_CELLS",
    "MAX_STRING",
    "SHA256_HEX_CHARS",
    "InvalidPayloadError",
    "optional_cell",
    "optional_scent",
    "reject_unknown_fields",
    "require_choice",
    "require_digest",
    "require_hint",
    "require_int",
    "require_mapping",
    "require_str",
]


def require_hint(payload: dict[str, Any], key: str = "hint", *, max_words: int = 15) -> str:
    """A required, non-empty Unicode hint within the negotiated word cap.

    Python strings may contain lone UTF-16 surrogates even though JSON text may
    not.  Control characters are also not natural-language content and make
    logs and line-oriented transports ambiguous, so both are refused.
    """
    value = require_str(payload, key)
    if not value.strip():
        raise InvalidPayloadError(f"{key!r} must not be blank")
    for character in value:
        category = unicodedata.category(character)
        if category == "Cs":
            raise InvalidPayloadError(f"{key!r} must contain Unicode scalar values")
        if category == "Cc":
            raise InvalidPayloadError(f"{key!r} contains a control character")
        if category == "Cf":
            raise InvalidPayloadError(f"{key!r} contains a Unicode format character")
    checked = policy_text(value)
    if NUMERIC.search(checked):
        raise InvalidPayloadError(f"{key!r} contains numeric coordinates")
    if FUTURE_ACTION.search(checked):
        raise InvalidPayloadError(f"{key!r} discloses a future action")
    count = len(value.split())
    if count > max_words:
        raise InvalidPayloadError(f"{key!r} has {count} words, over {max_words} words")
    return value
