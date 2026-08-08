"""The out-of-band control signal.

One of the three messages the cohort's reference format defines, split out of
:mod:`.protocol` for length. It travels *beside* the game rather than inside
it — enable, status, restart, quit — and is deliberately not part of the
sealed record the end-of-game audit replays.

Field names, field order, defaults and the exact text of every refusal are the
wire contract and are reproduced here verbatim.
"""

from dataclasses import asdict, dataclass
from typing import Any

from .protocol_roles import _require_role
from .validation import InvalidPayloadError, require_mapping, require_str

CONTROL_KINDS = frozenset({"enable", "status", "restart", "quit"})


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
