"""The four message shapes of ``wire_shape: reference-v3``.

Nulls are emitted explicitly rather than omitted, matching the reference's own wire. A receiver
should tolerate either — SPEC's stance everywhere is that unknown keys pass and absent optional
keys are silence — but a *sender* that matches the common shape gives the other side less to
guess about on a first meeting.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class TurnMessage:
    """One half-turn. The commit is sent; the nonce is withheld until the audit."""

    step: int
    sender: str                       # "police" | "thief"
    commit: str
    hint: str
    smell_grid: dict[str, float] = field(default_factory=dict)
    timestamp: str = ""
    barrier_placed: list[int] | None = None    # public by rule: the cop must declare truthfully
    capture_claim: list[int] | None = None     # police only: "I claim you are at [r,c]"
    claim_response: dict | None = None         # thief's obligatory honest answer
    win_claim: dict | None = None              # thief's {"type": "survival"}

    def to_wire(self) -> dict:
        return asdict(self)

    @classmethod
    def from_wire(cls, data: dict) -> "TurnMessage":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ControlMessage:
    """Out-of-band signalling — and the only way a refusal can travel.

    Every MCP tool in this shape returns ``{"ok": True}``, so a refusal *cannot* be a return
    value. It has to be pushed back as a control message, which is why this exists at all.
    """

    kind: str                          # "enable" | "status" | "restart" | "quit"
    sender: str
    sub_game_number: int = 1
    status: str = ""
    step_budget: float = 0.0
    payload: dict | None = None

    def to_wire(self) -> dict:
        return asdict(self)

    @classmethod
    def from_wire(cls, data: dict) -> "ControlMessage":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class AuditPayload:
    """End-of-game reveal: every record with its nonce, for the OPPONENT to re-hash."""

    sender: str
    records: list[dict]
    result_claim: str                  # "capture" | "survival" | "timeout"

    def to_wire(self) -> dict:
        return asdict(self)

    @classmethod
    def from_wire(cls, data: dict) -> "AuditPayload":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Negotiation:
    """The pre-game greeting.

    ``terms`` is the flat signed set — adding a key to it breaks the signature, which is why the
    pairing fields and the locked-model declarations ride *beside* it rather than inside it
    (SPEC sections 4, 7, 7.2).
    """

    terms: dict
    nonce: str
    signature: str
    group_id: str
    role: str | None = None                 # SPEC section 7.2
    sub_game_number: int | None = None      # SPEC section 7.2
    identity: dict = field(default_factory=dict)
    scent_model_sha256: str | None = None   # SPEC section 7
    wire_shape_sha256: str | None = None
    info_mode_sha256: str | None = None     # SPEC section 7 — the comparable (PROMOTED) form
    smell_binding_sha256: str | None = None  # SPEC section 7.4 — declaring `unbound` out loud
    info_mode: str | None = None            # bare-string form: kept for inbound tolerance; a
                                            # string and a hash are uncomparable, so it is silence
    game_uid: str | None = None             # SPEC section 7.3 — declared when the opponent is
                                            # known, so a wrong-input uid refuses at the handshake

    def to_wire(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_wire(cls, data: dict) -> "Negotiation":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
