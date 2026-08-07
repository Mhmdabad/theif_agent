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

import math
import re
import unicodedata
from typing import Any

from ..domain.hints import FUTURE_ACTION, NUMERIC, policy_text

MAX_STRING = 4096
"""Longest accepted string field. Bounded so a peer cannot be exhausted."""

SHA256_HEX_CHARS = 64
"""Length of a SHA-256 digest written as hexadecimal."""

_SHA256_HEX = re.compile(f"[0-9a-fA-F]{{{SHA256_HEX_CHARS}}}")

MAX_SCENT_CELLS = 10_000
"""Most cells an inbound scent field may name.

A bound on the message rather than on the board, because this layer does not
know the board: it is here so one payload cannot exhaust us before the layer
that *does* know the board gets to reject it on physics.
"""


class InvalidPayloadError(ValueError):
    """Raised when an inbound payload cannot be trusted.

    Callers convert this into a structured refusal rather than letting it
    escape as an exception across the wire.
    """


def require_mapping(payload: object, what: str = "payload") -> dict[str, Any]:
    """Accept only a JSON object."""
    if not isinstance(payload, dict):
        raise InvalidPayloadError(f"{what} must be an object, got {type(payload).__name__}")
    for key in payload:
        if not isinstance(key, str):
            raise InvalidPayloadError(f"{what} keys must be strings, got {type(key).__name__}")
    return payload


def require_str(payload: dict[str, Any], key: str, *, max_length: int = MAX_STRING) -> str:
    """A present, non-empty, length-bounded string."""
    if key not in payload:
        raise InvalidPayloadError(f"missing required field {key!r}")
    value = payload[key]
    if not isinstance(value, str):
        raise InvalidPayloadError(f"{key!r} must be a string, got {type(value).__name__}")
    if not value:
        raise InvalidPayloadError(f"{key!r} must not be empty")
    if len(value) > max_length:
        raise InvalidPayloadError(f"{key!r} exceeds {max_length} characters")
    return value


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


def require_digest(payload: dict[str, Any], key: str) -> str:
    """A SHA-256 digest, returned in the one spelling both peers hash to.

    Shape *and* spelling, because a digest is only ever used by comparing it.
    Anything that is not sixty-four hexadecimal characters cannot be a digest
    anyone computed, so letting it through would mean a consumer deciding
    mid-negotiation what to do with ``"unknown"`` — and the only safe answer
    there is the refusal that belongs at the door.

    Case is normalised rather than rejected. ``hexdigest()`` produces lowercase
    and that is the canonical form every comparison in this system is made
    against, but an opponent that upper-cases the same digest has not disagreed
    with us about anything, and refusing them would be a lost match over a
    spelling. Normalising here means the comparison downstream only ever sees
    canonical forms, so it never has to know this happened.
    """
    value = require_str(payload, key, max_length=SHA256_HEX_CHARS)
    if not _SHA256_HEX.fullmatch(value):
        raise InvalidPayloadError(
            f"{key!r} must be {SHA256_HEX_CHARS} hexadecimal characters, got {value!r}"
        )
    return value.lower()


def require_int(payload: dict[str, Any], key: str, *, minimum: int, maximum: int) -> int:
    """A present, in-range integer.

    Booleans are rejected explicitly. ``isinstance(True, int)`` is true in
    Python, so a payload of ``{"row": true}`` would otherwise pass as row 1.
    """
    if key not in payload:
        raise InvalidPayloadError(f"missing required field {key!r}")
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidPayloadError(f"{key!r} must be an integer, got {type(value).__name__}")
    if not minimum <= value <= maximum:
        raise InvalidPayloadError(f"{key!r} must be {minimum}..{maximum}, got {value}")
    return value


def require_choice(payload: dict[str, Any], key: str, allowed: frozenset[str]) -> str:
    """A string field restricted to a known set."""
    value = require_str(payload, key)
    if value not in allowed:
        raise InvalidPayloadError(f"{key!r} must be one of {sorted(allowed)}, got {value!r}")
    return value


def reject_unknown_fields(payload: dict[str, Any], allowed: frozenset[str]) -> None:
    """Refuse fields we do not expect.

    Silently ignoring extras lets a divergence in the wire contract go
    unnoticed until it matters — better to fail while it is still a handshake
    problem rather than a mid-match one.
    """
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise InvalidPayloadError(f"unexpected fields: {unknown}")


def optional_scent(payload: dict[str, Any], key: str) -> dict[str, float] | None:
    """A ``{"row,col": intensity}`` field, or absent.

    Shape only. Whether the cells exist on *this* board, and whether the
    intensities are ones the agreed model can produce, are questions about the
    game rather than about the wire — they belong to
    :func:`~..domain.scent_audit.check_field`, which knows the board size and
    the locked emission model. Splitting them keeps one validator per question
    instead of two that can disagree.

    What is refused here is what would be dangerous before anybody looks at the
    physics: a value that is not a number, a ``NaN`` that compares unequal to
    itself and would poison every sum downstream, an infinity that would
    dominate any normalisation, a negative intensity the rulebook's clamp makes
    meaningless, and a field too large to be about a board at all.

    Booleans are rejected explicitly: ``isinstance(True, int)`` is true in
    Python, so ``true`` would otherwise be absorbed as an intensity of one.
    """
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InvalidPayloadError(f"{key!r} must be an object, got {type(value).__name__}")
    if len(value) > MAX_SCENT_CELLS:
        raise InvalidPayloadError(f"{key!r} names {len(value)} cells, over {MAX_SCENT_CELLS}")
    field: dict[str, float] = {}
    for cell, intensity in value.items():
        if not isinstance(cell, str):
            raise InvalidPayloadError(f"{key!r} keys must be strings, got {type(cell).__name__}")
        if isinstance(intensity, bool) or not isinstance(intensity, int | float):
            raise InvalidPayloadError(
                f"{key!r} intensity at {cell!r} must be a number, got {type(intensity).__name__}"
            )
        if not math.isfinite(intensity):
            raise InvalidPayloadError(f"{key!r} intensity at {cell!r} must be finite")
        if intensity < 0.0:
            raise InvalidPayloadError(f"{key!r} intensity at {cell!r} must not be negative")
        field[cell] = float(intensity)
    return field


def optional_cell(payload: dict[str, Any], key: str) -> list[int] | None:
    """A ``[row, col]`` pair, or absent.

    Here rather than in :mod:`.protocol` because two message families now parse
    cells — turns and reveals — and a parser private to one of them would have
    been copied into the other.

    Accepts a list because that is what JSON carries; rejects anything that is
    not exactly two integers, since a malformed cell would otherwise be indexed.
    """
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise InvalidPayloadError(f"{key!r} must be a [row, col] pair, got {value!r}")
    for element in value:
        if isinstance(element, bool) or not isinstance(element, int):
            raise InvalidPayloadError(f"{key!r} coordinates must be integers, got {value!r}")
    return [int(value[0]), int(value[1])]
