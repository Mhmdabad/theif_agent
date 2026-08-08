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
from .validation import InvalidPayloadError, require_str


def _require_role(payload: dict[str, Any], key: str = "sender") -> str:
    value = require_str(payload, key)
    if value not in ROLES:
        raise InvalidPayloadError(f"{key!r} must be one of {sorted(ROLES)}, got {value!r}")
    return value
