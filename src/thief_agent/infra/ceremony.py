"""The four-phase Commit-Reveal ceremony, in the order the rulebook gives it.

Commit, Acknowledge, Reveal, Final Reveal. Each phase exists to remove one way
of cheating, and the order is the mechanism — a phase performed early gives
away exactly what the next phase was protecting.

**Why this is a separate module from** :mod:`.protocol`. The reference bundles
a turn into a single ``TurnMessage`` carrying the commitment *and* the hint
together, one round trip per turn. The rulebook does not: it puts an
Acknowledge between them, and says why — the acknowledgement *"ensures the
reveal happens only once both sides have already fixed their moves"* (Ch. 5.3.2).

Those are not the same protocol. Under the bundled form, whichever peer sends
second has already read the first one's hint before choosing what to commit to,
which is the precise advantage the Acknowledge phase exists to remove. The
rulebook is authoritative, so the ceremony here follows the book; the bundled
shape stays available through :class:`~.protocol.TurnMessage` for an opponent
who will only speak the reference dialect, and the divergence is recorded in
the README contradictions table.

Phase 1 is this module's smallest and strictest object. A commitment is a hash
and the bookkeeping needed to file it — nothing else. Any additional field is a
way to narrow the search space of what was committed to, and the move space is
small enough that narrowing it at all is fatal: five moves and a handful of
barrier cells means an opponent who learns *which cells were even candidates*
can hash the remainder in microseconds.
"""

import re
from dataclasses import dataclass
from typing import Any

from ..domain.actions import ROLES
from .validation import InvalidPayloadError, require_int, require_mapping, require_str

DIGEST = re.compile(r"^[0-9a-f]{64}$")
"""A SHA-256 digest as ``hexdigest`` renders it: 64 lowercase hex characters.

Checked rather than assumed. An uppercase or truncated digest still compares
unequal to ours, so it would surface as a forgery verdict against an opponent
whose only crime was formatting — and a forgery verdict is unappealable.
"""

COMMIT_FIELDS = ("step", "sender", "commit", "timestamp")
"""Everything phase 1 may carry. The tuple is the specification, not a hint."""


class CeremonyError(ValueError):
    """Raised when a phase message is malformed or arrives out of order."""


@dataclass(frozen=True, slots=True)
class Commitment:
    """Phase 1. The hash crosses the wire; nothing that could reverse it does.

    Frozen because a commitment that could be edited after construction is not
    a commitment. The whole value of the phase is that this object is fixed
    before the opponent's is known.
    """

    step: int
    sender: str
    commit: str
    timestamp: str

    def __post_init__(self) -> None:
        if self.sender not in ROLES:
            raise CeremonyError(f"sender must be one of {sorted(ROLES)}, got {self.sender!r}")
        if self.step < 0:
            raise CeremonyError(f"step must be >= 0, got {self.step}")
        if not DIGEST.match(self.commit):
            raise CeremonyError(
                f"commit must be 64 lowercase hex characters, got {self.commit!r}; "
                "a malformed digest would surface later as a forgery verdict "
                "against an opponent whose only mistake was formatting"
            )

    def to_dict(self) -> dict[str, Any]:
        """The wire form. Exactly :data:`COMMIT_FIELDS` and never more."""
        return {
            "step": self.step,
            "sender": self.sender,
            "commit": self.commit,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: object) -> "Commitment":
        """Parse an inbound commitment, ignoring anything extra.

        Extra keys are dropped rather than refused. We cannot stop an opponent
        putting their move in the message, and refusing would let them end our
        match by sending one — but we can decline to *read* it, so nothing
        downstream can act on information phase 1 was not supposed to carry.

        Raises:
            CeremonyError: on anything we would not want to file.
        """
        try:
            body = require_mapping(data, "commitment")
            return cls(
                step=require_int(body, "step", minimum=0, maximum=10_000),
                sender=require_str(body, "sender"),
                commit=require_str(body, "commit"),
                timestamp=require_str(body, "timestamp"),
            )
        except InvalidPayloadError as exc:
            raise CeremonyError(str(exc)) from exc
