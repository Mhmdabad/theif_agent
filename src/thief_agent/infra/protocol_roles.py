"""Who a message claims to be from.

Every shape on this wire — turn, audit, control signal — names a sender, and
every one of them rejects an unrecognised name the same way. That shared check
lives here, below the individual message modules, so the three cannot drift
apart in what they will accept as a role.

Split out of :mod:`.protocol` for length. The check itself, and the exact text
it refuses with, are unchanged: they are part of the wire contract.
"""

from typing import Any

from ..domain.actions import ROLES as ROLES
from .validation import SHA256_HEX_CHARS, InvalidPayloadError, require_str


def _require_role(payload: dict[str, Any], key: str = "sender") -> str:
    value = require_str(payload, key)
    if value not in ROLES:
        raise InvalidPayloadError(f"{key!r} must be one of {sorted(ROLES)}, got {value!r}")
    return value


def _require_commit(payload: dict[str, Any]) -> str:
    """A commitment: sixty-four lowercase hex characters, exactly.

    Case matters because the digest is compared as a *string*, never re-parsed
    as a number. An uppercase commitment is arithmetically the same value and
    textually a different one, so accepting it means an honest peer's turn
    fails to match its own reveal and reads as forgery.
    """
    value = require_str(payload, "commit")
    if len(value) != SHA256_HEX_CHARS or any(c not in "0123456789abcdef" for c in value):
        raise InvalidPayloadError(
            f"'commit' must be {SHA256_HEX_CHARS} lowercase hex characters; "
            "the digest is compared as a string, so case is not cosmetic"
        )
    return value


def _require_numeric(grid: dict[str, object]) -> None:
    """Every intensity a real number, not a string that looks like one.

    ``float("0.9")`` succeeds, so a quoted intensity survives a parser that
    coerces and only shows up later, as arithmetic on a value nobody meant to
    send. Booleans are excluded too: ``True`` is an ``int`` in Python and would
    otherwise pass as an intensity of one.
    """
    for cell, value in grid.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise InvalidPayloadError(
                f"'smell_grid[{cell}]' must be a number, got {type(value).__name__}; "
                "a quoted intensity survives JSON and then poisons the arithmetic"
            )
