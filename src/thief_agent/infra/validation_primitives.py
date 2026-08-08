"""General-purpose payload primitives shared by every validator.

The type discipline that has nothing to do with this game: the refusal type
itself, the length bound, and the scalar field readers every message family
needs. Kept apart from the game-specific checks so a rule about hints or scent
cannot be changed by editing something as load-bearing as ``require_str``.
"""

import re
from typing import Any

MAX_STRING = 4096
"""Longest accepted string field. Bounded so a peer cannot be exhausted."""

SHA256_HEX_CHARS = 64
"""Length of a SHA-256 digest written as hexadecimal."""

_SHA256_HEX = re.compile(f"[0-9a-fA-F]{{{SHA256_HEX_CHARS}}}")


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
