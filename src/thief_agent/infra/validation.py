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

from typing import Any

MAX_STRING = 4096
"""Longest accepted string field. Bounded so a peer cannot be exhausted."""


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
