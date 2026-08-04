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


ACK_FIELDS = ("step", "sender", "acknowledges", "timestamp")
"""Everything phase 2 may carry."""


@dataclass(frozen=True, slots=True)
class Acknowledgement:
    """Phase 2. *I have your commitment and I am locked on it.*

    The rulebook gives this phase one job and states it plainly: the
    acknowledgement *"ensures the reveal happens only once both sides have
    already fixed their moves"*. It does two things at once — it stops the
    sender walking back a commitment we have already seen, and it stops us
    revealing into a peer who has not committed yet.

    ``acknowledges`` carries the digest being acknowledged rather than a bare
    "yes". A yes is unfalsifiable: a peer that later claims it acknowledged a
    *different* commitment cannot be contradicted by it, and the whole phase
    turns on being able to say precisely what was locked.
    """

    step: int
    sender: str
    acknowledges: str
    timestamp: str

    def __post_init__(self) -> None:
        if self.sender not in ROLES:
            raise CeremonyError(f"sender must be one of {sorted(ROLES)}, got {self.sender!r}")
        if self.step < 0:
            raise CeremonyError(f"step must be >= 0, got {self.step}")
        if not DIGEST.match(self.acknowledges):
            raise CeremonyError(
                f"acknowledges must be 64 lowercase hex characters, got {self.acknowledges!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "sender": self.sender,
            "acknowledges": self.acknowledges,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: object) -> "Acknowledgement":
        """Parse an inbound acknowledgement.

        Raises:
            CeremonyError: on anything we would not want to act on.
        """
        try:
            body = require_mapping(data, "acknowledgement")
            return cls(
                step=require_int(body, "step", minimum=0, maximum=10_000),
                sender=require_str(body, "sender"),
                acknowledges=require_str(body, "acknowledges"),
                timestamp=require_str(body, "timestamp"),
            )
        except InvalidPayloadError as exc:
            raise CeremonyError(str(exc)) from exc


@dataclass
class StepCeremony:
    """The four phases of one step, and what is permitted at each point.

    A mutable object among frozen ones, deliberately: the messages are
    evidence and must not change, while *how far we have got* is the one thing
    that legitimately does.

    The invariant the whole class exists for is :attr:`locked` — nothing may be
    revealed until both peers hold each other's commitment and have said so.
    Everything else here is bookkeeping in service of that one question.
    """

    step: int
    role: str
    ours: Commitment | None = None
    theirs: Commitment | None = None
    ack_sent: Acknowledgement | None = None
    ack_received: Acknowledgement | None = None

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise CeremonyError(f"role must be one of {sorted(ROLES)}, got {self.role!r}")

    def commit(self, ours: Commitment) -> Commitment:
        """File our own commitment for this step.

        Raises:
            CeremonyError: on a second commitment, or one for another step or
                role. Re-committing is the move this ceremony exists to
                prevent, and it is not less serious for being local.
        """
        if self.ours is not None:
            raise CeremonyError(
                f"step {self.step} is already committed; a commitment is not revisable"
            )
        self._check_belongs(ours.step, ours.sender, expected_role=self.role, what="commitment")
        self.ours = ours
        return ours

    def receive(self, theirs: Commitment) -> Commitment:
        """File the opponent's commitment.

        Raises:
            CeremonyError: if they commit twice, or for the wrong step or role.
                A second commitment for one step is either a bug on their side
                or an attempt to replace a move, and we cannot tell which.
        """
        if self.theirs is not None:
            raise CeremonyError(
                f"the opponent already committed to step {self.step}; "
                "a second commitment would replace a move that is already locked"
            )
        self._check_belongs(
            theirs.step, theirs.sender, expected_role=self.opponent, what="commitment"
        )
        self.theirs = theirs
        return theirs

    def acknowledge(self, timestamp: str) -> Acknowledgement:
        """Confirm we are locked on their commitment.

        Raises:
            CeremonyError: if they have not committed. Acknowledging nothing is
                worse than not acknowledging: it tells them they may reveal,
                against a step we have no record of.
        """
        if self.theirs is None:
            raise CeremonyError(
                f"nothing to acknowledge at step {self.step}; the opponent has not committed, "
                "and acknowledging would tell them to reveal into a step we cannot check"
            )
        self.ack_sent = Acknowledgement(
            step=self.step,
            sender=self.role,
            acknowledges=self.theirs.commit,
            timestamp=timestamp,
        )
        return self.ack_sent

    def receive_ack(self, ack: Acknowledgement) -> Acknowledgement:
        """File their acknowledgement of *our* commitment.

        Raises:
            CeremonyError: if we have not committed, if it is for the wrong
                step or role, or if the digest is not the one we sent. That
                last case is the one worth the check: an acknowledgement of
                some other digest is not a weaker lock, it is a lock on a
                commitment we never made.
        """
        if self.ours is None:
            raise CeremonyError(f"acknowledgement for step {self.step} arrived before we committed")
        self._check_belongs(
            ack.step, ack.sender, expected_role=self.opponent, what="acknowledgement"
        )
        if ack.acknowledges != self.ours.commit:
            raise CeremonyError(
                f"they acknowledged {ack.acknowledges[:16]}… but we committed "
                f"{self.ours.commit[:16]}…; that is a lock on a commitment we never made"
            )
        self.ack_received = ack
        return ack

    @property
    def opponent(self) -> str:
        """The role that is not ours."""
        return next(role for role in sorted(ROLES) if role != self.role)

    @property
    def locked(self) -> bool:
        """Whether both sides have committed *and* said so.

        The gate the rulebook puts between Commit and Reveal. All four have to
        be in: our commitment, theirs, our acknowledgement of theirs and theirs
        of ours. Three out of four is a peer that can still change its mind.
        """
        return all(
            part is not None for part in (self.ours, self.theirs, self.ack_sent, self.ack_received)
        )

    def _check_belongs(self, step: int, sender: str, expected_role: str, what: str) -> None:
        if step != self.step:
            raise CeremonyError(f"{what} is for step {step}, this ceremony is step {self.step}")
        if sender != expected_role:
            raise CeremonyError(f"{what} is from {sender!r}, expected {expected_role!r}")
