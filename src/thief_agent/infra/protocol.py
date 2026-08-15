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

from .protocol_control import CONTROL_KINDS, ControlMessage
from .protocol_roles import ROLES, _require_commit, _require_numeric, _require_role
from .validation import (
    InvalidPayloadError,
    optional_cell,
    require_int,
    require_mapping,
    require_str,
)

__all__ = [
    "CONTROL_KINDS",
    "ROLES",
    "AuditPayload",
    "ControlMessage",
    "TurnMessage",
]


def _wire(body: dict[str, Any], game_uid: str, sub_game: int) -> dict[str, Any]:
    """Drop our own binding fields when unset, leaving the cohort's shape.

    The reference parses both messages with ``cls(**data)``, which raises on
    any field it does not declare — so sending ours unconditionally would make
    every message unreadable to a peer running the cohort's code. A refused
    audit is worse than a refused turn: an unopenable commitment, which rule 19
    reads as forgery rather than as a parse error.
    """
    if not game_uid:
        body.pop("game_uid", None)
    if not sub_game:
        body.pop("sub_game", None)
    return body


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
    game_uid: str = ""
    """Which series this turn belongs to. **Ours, not the cohort's** — the
    reference protocol has no such field. Absent inbound is never an error; see
    :func:`_wire` and :meth:`~.inboxes_gate.InboxGate._closed`."""

    sub_game: int = 0
    """How far along that series. Absent means "the one we are bound to"."""
    barrier_placed: list[int] | None = None
    capture_claim: list[int] | None = None
    claim_response: dict[str, Any] | None = None
    win_claim: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """The wire form, with our own fields dropped when unset."""
        return _wire(asdict(self), self.game_uid, self.sub_game)

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
        _require_numeric(smell)
        return cls(
            step=require_int(body, "step", minimum=0, maximum=10_000),
            sender=_require_role(body),
            hint=body.get("hint", "") if isinstance(body.get("hint", ""), str) else "",
            smell_grid={str(k): float(v) for k, v in smell.items()},
            commit=_require_commit(body),
            timestamp=require_str(body, "timestamp"),
            game_uid=str(body.get("game_uid", "")),
            sub_game=int(body.get("sub_game", 0) or 0),
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
    game_uid: str = ""
    """Ours, not the cohort's — see :attr:`TurnMessage.game_uid`."""

    sub_game: int = 0

    def to_dict(self) -> dict[str, Any]:
        """The wire form, with our own fields dropped when unset."""
        return _wire(asdict(self), self.game_uid, self.sub_game)

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
            game_uid=str(body.get("game_uid", "")),
            sub_game=int(body.get("sub_game", 0) or 0),
        )
