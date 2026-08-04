"""The wire format, as the cohort speaks it.

These shapes are **not ours to choose**. They match the course reference
implementation, which ships with the book and is the only thing resembling a
shared standard across the cohort. A better protocol nobody speaks is worthless.

Two properties are worth stating because they differ from what we built first:

**One message carries a whole turn.** Hint, scent, commitment, barrier
declaration and capture claim travel together in a single ``TurnMessage``, one
round trip per turn — rather than being split across separate calls. That is
also closer to what the rulebook describes.

**The turn token travels with the message.** Receiving a ``TurnMessage`` *is*
what makes it your turn. There is no separate handoff to get out of step with.

Validation lives here rather than on the far side. The reference validates
nothing, so accepting its format costs us nothing in safety: we parse strictly,
refuse what we cannot trust, and remain wire-compatible.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from ..domain.actions import ROLES as ROLES
from .validation import (
    InvalidPayloadError,
    optional_cell,
    require_int,
    require_mapping,
    require_str,
)

CONTROL_KINDS = frozenset({"enable", "status", "restart", "quit"})


def _require_role(payload: dict[str, Any], key: str = "sender") -> str:
    value = require_str(payload, key)
    if value not in ROLES:
        raise InvalidPayloadError(f"{key!r} must be one of {sorted(ROLES)}, got {value!r}")
    return value


@dataclass
class TurnMessage:
    """Everything one peer tells the other about its turn — and nothing more.

    The true position, move and verdict are **not** here in the clear. They are
    sealed inside ``commit`` and proven only at the end-of-game audit.
    """

    step: int
    sender: str
    hint: str
    smell_grid: dict[str, float]
    commit: str
    timestamp: str
    barrier_placed: list[int] | None = None
    capture_claim: list[int] | None = None
    claim_response: dict[str, Any] | None = None
    win_claim: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> "TurnMessage":
        """Parse and validate an inbound turn.

        Raises:
            InvalidPayloadError: on anything we would not want to act on. The
                opponent is untrusted, and a malformed turn that crashed us
                mid-match would be a technical loss scoring zero for both.
        """
        body = require_mapping(data, "turn message")
        smell = body.get("smell_grid", {})
        if not isinstance(smell, dict):
            raise InvalidPayloadError(f"'smell_grid' must be an object, got {type(smell).__name__}")
        return cls(
            step=require_int(body, "step", minimum=0, maximum=10_000),
            sender=_require_role(body),
            hint=body.get("hint", "") if isinstance(body.get("hint", ""), str) else "",
            smell_grid={str(k): float(v) for k, v in smell.items()},
            commit=require_str(body, "commit"),
            timestamp=require_str(body, "timestamp"),
            barrier_placed=optional_cell(body, "barrier_placed"),
            capture_claim=optional_cell(body, "capture_claim"),
            claim_response=body.get("claim_response"),
            win_claim=body.get("win_claim"),
        )


@dataclass
class AuditPayload:
    """End-of-game reveal: the sealed records, so the opponent can re-verify."""

    sender: str
    records: list[dict[str, Any]] = field(default_factory=list)
    result_claim: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> "AuditPayload":
        body = require_mapping(data, "audit payload")
        records = body.get("records", [])
        if not isinstance(records, list):
            raise InvalidPayloadError(f"'records' must be a list, got {type(records).__name__}")
        return cls(
            sender=_require_role(body),
            records=[require_mapping(r, "audit record") for r in records],
            result_claim=require_str(body, "result_claim"),
        )


@dataclass
class ControlMessage:
    """Out-of-band control signal. **Not** part of the sealed game record."""

    kind: str
    sender: str
    sub_game_number: int = 1
    status: str = ""
    step_budget: float = 0.0
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> "ControlMessage":
        body = require_mapping(data, "control message")
        kind = require_str(body, "kind")
        if kind not in CONTROL_KINDS:
            raise InvalidPayloadError(
                f"'kind' must be one of {sorted(CONTROL_KINDS)}, got {kind!r}"
            )
        return cls(
            kind=kind,
            sender=_require_role(body),
            sub_game_number=int(body.get("sub_game_number", 1)),
            status=str(body.get("status", "")),
            step_budget=float(body.get("step_budget", 0.0)),
            payload=body.get("payload"),
        )
