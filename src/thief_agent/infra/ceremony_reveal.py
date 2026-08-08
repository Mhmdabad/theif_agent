"""Phase 3 of the ceremony: the disclosure that still withholds the nonce."""

from dataclasses import dataclass
from typing import Any

from ..domain.actions import ROLES
from ..domain.bluff import INTENTS
from .ceremony_errors import CeremonyError
from .validation import (
    InvalidPayloadError,
    optional_cell,
    optional_scent,
    require_hint,
    require_int,
    require_mapping,
    require_str,
)

REVEAL_FIELDS = (
    "step",
    "sender",
    "move",
    "intent",
    "hint",
    "barrier_placed",
    "scent",
    "timestamp",
    "game_uid",
    "sub_game",
)
"""Everything phase 3 may carry. Conspicuously not the nonce.

``scent`` is here and **not** in :data:`COMMIT_FIELDS`, which is the one
placement decision in this module that is about the pheromone layer rather than
about the ceremony. A fresh emission peaks on the emitter's own cell, so a
field sent alongside the commitment would disclose the exact position the
commitment exists to conceal — the reference dialect's ``TurnMessage`` bundles
the two and gives that away every turn. Held to phase 3, the field arrives only
once both sides are locked, and it is still bound by the phase-1 digest, so
nothing about it is chosen after hearing what the opponent said.
"""


@dataclass(frozen=True, slots=True)
class Reveal:
    """Phase 3. The action and the sentence — and still not the nonce.

    The rulebook is explicit about the omission: *"the Nonce stays hidden at
    this stage, to prevent reverse-engineering the signatures prematurely"*.
    That is not caution about this step. Every commitment in the match uses
    the same construction, so one exposed nonce turns the commitment for
    *every* other step into a hash whose only unknown is a five-way move — and
    the opponent still has steps left to play against it.

    **Nothing here can be verified when it is acted upon.** The digest cannot
    be recomputed without the nonce, so a reveal is believed on the strength of
    the lock and checked only at the final audit. That gap is the design, not
    a weakness in it: it is what lets both peers act inside a turn, and it is
    exactly why an audit failure is unappealable rather than negotiable — the
    cheat has already had its effect and the only remedy left is the result.
    """

    step: int
    sender: str
    move: str
    intent: str
    hint: str
    timestamp: str
    game_uid: str = "series-123"
    sub_game: int = 2
    barrier_placed: list[int] | None = None
    scent: dict[str, float] | None = None
    """The trail this step laid, as ``{"row,col": intensity}``.

    Optional on the wire and **not** optional at the audit. A peer that omits
    it has disclosed nothing checkable, which
    :func:`~..domain.scent_audit.audit_scent` treats as a failure unless the
    series was explicitly negotiated without scent binding. Parsing it as
    absent rather than refusing the message is deliberate: refusing would let
    any opponent end our match by leaving out a key, and the correct place to
    lose a match over unverifiable scent is the verdict, not the parser.
    """

    def __post_init__(self) -> None:
        if self.sender not in ROLES:
            raise CeremonyError(f"sender must be one of {sorted(ROLES)}, got {self.sender!r}")
        if self.step < 0:
            raise CeremonyError(f"step must be >= 0, got {self.step}")
        if self.intent not in INTENTS:
            raise CeremonyError(f"intent must be one of {sorted(INTENTS)}, got {self.intent!r}")
        if not self.game_uid:
            raise CeremonyError("game_uid must not be empty")
        if not 1 <= self.sub_game <= 6:
            raise CeremonyError(f"sub_game must be between 1 and 6, got {self.sub_game}")

    def to_dict(self) -> dict[str, Any]:
        """The wire form. :data:`REVEAL_FIELDS`, and no nonce in it."""
        return {
            "step": self.step,
            "sender": self.sender,
            "move": self.move,
            "intent": self.intent,
            "hint": self.hint,
            "barrier_placed": self.barrier_placed,
            "scent": self.scent,
            "timestamp": self.timestamp,
            "game_uid": self.game_uid,
            "sub_game": self.sub_game,
        }

    @classmethod
    def from_dict(cls, data: object, *, hint_max_words: int = 15) -> "Reveal":
        """Parse an inbound reveal.

        A nonce arriving here is **refused**, not ignored. Every other stray
        field in this module is dropped quietly, because reading less is always
        safe — but a nonce is the one value whose early arrival means the
        opponent has misunderstood the ceremony, and continuing would let us
        hold a secret we are not supposed to have until the audit. Better to
        stop than to be in possession of it.

        Raises:
            CeremonyError: on anything malformed, or on a nonce.
        """
        try:
            body = require_mapping(data, "reveal")
            if "nonce" in body:
                raise CeremonyError(
                    f"reveal for step {body.get('step')} carries a nonce; it is withheld until "
                    "the final audit, and one early nonce weakens every other commitment"
                )
            return cls(
                step=require_int(body, "step", minimum=0, maximum=10_000),
                sender=require_str(body, "sender"),
                move=require_str(body, "move"),
                intent=require_str(body, "intent"),
                hint=require_hint(body, max_words=hint_max_words),
                timestamp=require_str(body, "timestamp"),
                game_uid=require_str(body, "game_uid"),
                sub_game=require_int(body, "sub_game", minimum=1, maximum=6),
                barrier_placed=optional_cell(body, "barrier_placed"),
                scent=optional_scent(body, "scent"),
            )
        except InvalidPayloadError as exc:
            raise CeremonyError(str(exc)) from exc
