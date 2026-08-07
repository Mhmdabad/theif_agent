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
import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..domain.actions import ROLES
from ..domain.bluff import INTENTS
from ..domain.board import BoardState
from ..domain.crypto import NONCE_BYTES, commit_of, step_record
from .validation import (
    InvalidPayloadError,
    optional_cell,
    optional_scent,
    require_hint,
    require_int,
    require_mapping,
    require_str,
)

DIGEST = re.compile(r"^[0-9a-f]{64}$")
"""A SHA-256 digest as ``hexdigest`` renders it: 64 lowercase hex characters.

Checked rather than assumed. An uppercase or truncated digest still compares
unequal to ours, so it would surface as a forgery verdict against an opponent
whose only crime was formatting — and a forgery verdict is unappealable.
"""

NONCE_LENGTH = NONCE_BYTES * 2
NONCE = re.compile(rf"^[0-9a-f]{{{NONCE_LENGTH}}}$")
"""A nonce as :func:`~..domain.crypto.nonce` renders it."""

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


REVEAL_FIELDS = (
    "step",
    "sender",
    "move",
    "intent",
    "hint",
    "barrier_placed",
    "scent",
    "timestamp",
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
                barrier_placed=optional_cell(body, "barrier_placed"),
                scent=optional_scent(body, "scent"),
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
    revealed_ours: Reveal | None = None
    revealed_theirs: Reveal | None = None
    our_nonce: str | None = None
    """The secret this step will disclose in phase 4, and not before.

    Held by the ceremony rather than by the message, which is the whole point:
    :class:`Commitment` cannot carry it and :class:`Reveal` refuses it, so the
    only path from here to the wire is the final reveal.
    """

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise CeremonyError(f"role must be one of {sorted(ROLES)}, got {self.role!r}")

    def commit(self, ours: Commitment, nonce: str) -> Commitment:
        """File our own commitment for this step, and keep the nonce that opens it.

        The nonce arrives here rather than staying with the caller because this
        object is what discloses it in phase 4. A secret held somewhere else is
        a secret with a second path to the wire.

        Raises:
            CeremonyError: on a second commitment, one for another step or
                role, or a malformed nonce. Re-committing is the move this
                ceremony exists to prevent, and it is not less serious for
                being local.
        """
        if self.ours is not None:
            raise CeremonyError(
                f"step {self.step} is already committed; a commitment is not revisable"
            )
        if not NONCE.match(nonce):
            raise CeremonyError(f"nonce is not {NONCE_LENGTH} hex characters: {nonce!r}")
        self._check_belongs(ours.step, ours.sender, expected_role=self.role, what="commitment")
        self.ours = ours
        self.our_nonce = nonce
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

    def reveal(self, opened: Reveal) -> Reveal:
        """Disclose our action and hint, once and only once both sides are locked.

        Raises:
            CeremonyError: if the lock is incomplete, or on a second reveal.
                Revealing early is not an efficiency — it hands the opponent
                our move while theirs is still free to change, which is the one
                thing the acknowledgement was for.
        """
        if not self.locked:
            raise CeremonyError(
                f"cannot reveal step {self.step} before both sides are locked ({self.pending()}); "
                "revealing early hands over our move while theirs can still change"
            )
        if self.revealed_ours is not None:
            raise CeremonyError(f"step {self.step} is already revealed; a reveal is not revisable")
        self._check_belongs(opened.step, opened.sender, expected_role=self.role, what="reveal")
        self.revealed_ours = opened
        return opened

    def receive_reveal(self, opened: Reveal) -> Reveal:
        """File the opponent's disclosure. **It cannot be checked yet.**

        The digest cannot be recomputed without their nonce, so this is
        believed on the strength of the lock and verified only at the final
        audit. Storing it is therefore the whole job: a reveal we did not keep
        is a step the audit cannot re-derive, and an audit that cannot
        re-derive a step proves nothing about it either way.

        Raises:
            CeremonyError: if they have not committed, if we are not locked, or
                on a second reveal for the step.
        """
        if not self.locked:
            raise CeremonyError(
                f"the opponent revealed step {self.step} before both sides were locked "
                f"({self.pending()}); accepting it would reward revealing early"
            )
        if self.revealed_theirs is not None:
            raise CeremonyError(
                f"the opponent already revealed step {self.step}; "
                "a second disclosure would replace an action we have acted on"
            )
        self._check_belongs(opened.step, opened.sender, expected_role=self.opponent, what="reveal")
        self.revealed_theirs = opened
        return opened

    def pending(self) -> str:
        """Which parts of the lock are still missing. For the error, and the log."""
        missing = [
            name
            for name, part in (
                ("our commitment", self.ours),
                ("their commitment", self.theirs),
                ("our acknowledgement", self.ack_sent),
                ("their acknowledgement", self.ack_received),
            )
            if part is None
        ]
        return "missing " + ", ".join(missing) if missing else "locked"

    def _check_belongs(self, step: int, sender: str, expected_role: str, what: str) -> None:
        if step != self.step:
            raise CeremonyError(f"{what} is for step {step}, this ceremony is step {self.step}")
        if sender != expected_role:
            raise CeremonyError(f"{what} is from {sender!r}, expected {expected_role!r}")


@dataclass(frozen=True, slots=True)
class FinalReveal:
    """Phase 4. Every nonce of the match, disclosed at once, at the end.

    **At once and at the end are both load-bearing.** A nonce released while
    the match is running reopens the commitment it belongs to, and because
    every step uses the same construction it also narrows every other one — so
    the rulebook's *"only at the end of the whole game are all the Nonce values
    revealed"* is a single event by necessity rather than by tidiness.

    Disclosing them **all** matters for the opposite reason. A step whose nonce
    is missing is a step nobody can re-derive, and an audit that cannot
    re-derive a step proves nothing about it either way — which is exactly the
    step a cheat would omit. A partial final reveal is therefore refused rather
    than partially accepted.
    """

    sender: str
    nonces: dict[int, str]
    timestamp: str

    def __post_init__(self) -> None:
        if self.sender not in ROLES:
            raise CeremonyError(f"sender must be one of {sorted(ROLES)}, got {self.sender!r}")
        for step, value in sorted(self.nonces.items()):
            if step < 0:
                raise CeremonyError(f"step must be >= 0, got {step}")
            if not NONCE.match(value):
                raise CeremonyError(
                    f"nonce for step {step} is not {NONCE_LENGTH} hex characters: {value!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        """The wire form. Step keys become strings, as JSON requires."""
        return {
            "sender": self.sender,
            "nonces": {str(step): value for step, value in sorted(self.nonces.items())},
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: object) -> "FinalReveal":
        """Parse an inbound final reveal.

        Raises:
            CeremonyError: on anything malformed. A step key that is not an
                integer is refused rather than skipped: a nonce we cannot file
                against a step is a nonce that verifies nothing, and silently
                dropping it would turn their formatting error into our
                unverifiable step.
        """
        try:
            body = require_mapping(data, "final reveal")
            raw = body.get("nonces")
            if not isinstance(raw, dict):
                raise CeremonyError(f"'nonces' must be an object, got {type(raw).__name__}")
            nonces: dict[int, str] = {}
            for key, value in raw.items():
                try:
                    step = int(key)
                except (TypeError, ValueError) as exc:
                    raise CeremonyError(f"step key {key!r} is not an integer") from exc
                if not isinstance(value, str):
                    raise CeremonyError(f"nonce for step {step} is not a string")
                nonces[step] = value
            return cls(
                sender=require_str(body, "sender"),
                nonces=nonces,
                timestamp=require_str(body, "timestamp"),
            )
        except InvalidPayloadError as exc:
            raise CeremonyError(str(exc)) from exc


@dataclass
class MatchCeremony:
    """Every step's ceremony, and the one event that ends them all.

    Exists so phase 4 has something to be complete *against*. A final reveal is
    only meaningful relative to the set of steps that were played, and no
    individual :class:`StepCeremony` knows how many of those there were.
    """

    role: str
    steps: dict[int, StepCeremony] = field(default_factory=dict)
    over: bool = False

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise CeremonyError(f"role must be one of {sorted(ROLES)}, got {self.role!r}")

    def at(self, step: int) -> StepCeremony:
        """The ceremony for ``step``, opening one if this is its first message."""
        if step not in self.steps:
            self.steps[step] = StepCeremony(step=step, role=self.role)
        return self.steps[step]

    def finish(self) -> None:
        """Mark the match over. Only after this may nonces be disclosed."""
        self.over = True

    def final_reveal(self, timestamp: str) -> FinalReveal:
        """Disclose every nonce of the match, at the end, in one message.

        Raises:
            CeremonyError: while the match is still running, or if any step
                cannot contribute a nonce. Both refusals protect the same
                thing from opposite sides — an early disclosure reopens
                commitments that still matter, and a partial one leaves a step
                nobody can re-derive, which is precisely the step a cheat would
                omit.
        """
        if not self.over:
            raise CeremonyError(
                "cannot disclose nonces while the match is running; every step uses the "
                "same construction, so one released early narrows all the others"
            )
        missing = sorted(step for step, one in self.steps.items() if one.our_nonce is None)
        if missing:
            raise CeremonyError(
                f"no nonce recorded for step(s) {missing}; a step nobody can re-derive "
                "proves nothing at audit, which is what makes a partial reveal worse "
                "than a late one"
            )
        return FinalReveal(
            sender=self.role,
            nonces={step: one.our_nonce for step, one in self.steps.items() if one.our_nonce},
            timestamp=timestamp,
        )

    def receive_final_reveal(self, disclosed: FinalReveal) -> FinalReveal:
        """File the opponent's nonces, checking they cover what they committed to.

        Raises:
            CeremonyError: if it comes from the wrong role, or omits a step
                they committed to. Extra steps are tolerated — a nonce for a
                step we have no record of verifies nothing and harms nothing —
                but a **missing** one is the shape of a hidden move.
        """
        if disclosed.sender != self.opponent:
            raise CeremonyError(
                f"final reveal is from {disclosed.sender!r}, expected {self.opponent!r}"
            )
        owed = {step for step, one in self.steps.items() if one.theirs is not None}
        absent = sorted(owed - set(disclosed.nonces))
        if absent:
            raise CeremonyError(
                f"their final reveal omits step(s) {absent}, which they committed to; "
                "an unopenable commitment is indistinguishable from a hidden move"
            )
        return disclosed

    @property
    def opponent(self) -> str:
        """The role that is not ours."""
        return next(role for role in sorted(ROLES) if role != self.role)


class Verdict(Enum):
    """What the audit concluded about one peer's play."""

    CLEAN = "clean"
    FORGED = "forged"


@dataclass(frozen=True, slots=True)
class AuditResult:
    """Every step re-derived, and what that showed.

    Carries the failures rather than only the verdict. Both teams must **agree**
    a result before either may report it, and "you cheated" is not a claim
    anyone concedes — "step 12 committed to a digest that your own revealed
    move and nonce do not produce" is, because they can run the same
    arithmetic and get the same answer.
    """

    verdict: Verdict
    checked: int
    failures: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return self.verdict is Verdict.CLEAN

    def __str__(self) -> str:
        if self.clean:
            return f"{self.checked} steps re-derived, all matching"
        return f"{self.checked} steps re-derived, {len(self.failures)} failed: " + "; ".join(
            self.failures
        )


def verify_step(record: dict[str, Any], nonce: str, commit: str) -> bool:
    """Whether ``record`` under ``nonce`` really produces ``commit``.

    Compared with :func:`secrets.compare_digest` rather than ``==``, as the
    rulebook specifies. Being honest about why: by audit time both digests are
    public, so the timing channel here leaks nothing anyone does not already
    have. The reason to use it anyway is that ``==`` on a digest is a habit,
    and the habit is what eventually gets applied to a comparison where the
    timing *does* matter — and a project that hashes for a living should not be
    growing that habit.
    """
    return secrets.compare_digest(commit_of(record, nonce), commit)


def audit_opponent(
    match: MatchCeremony,
    disclosed: FinalReveal,
    sealed_states: dict[int, BoardState],
) -> AuditResult:
    """Re-derive every step the opponent committed to, and say whether it holds.

    ``sealed_states`` is the board they sealed against at each step, supplied
    by the caller: reconstructing their trajectory is a different job from
    checking arithmetic, and mixing the two would make a reconstruction bug
    indistinguishable from a forgery.

    The record is rebuilt through :func:`~..domain.crypto.step_record` — the
    same function the committer used, not a re-implementation of it. An audit
    with its own assembly path would report forgery whenever the two paths
    drifted, which is the one verdict that must never be reachable by accident.

    A step is a failure if we cannot rebuild it *or* if the rebuild disagrees.
    Those are reported separately: a missing reveal and a wrong digest are
    different accusations, and only one of them is provable tampering.

    **Every step is checked before returning.** Stopping at the first failure
    would be faster and would hand the opponent an incomplete accusation — they
    are entitled to see the whole list, and a dispute settled on one step tends
    to be reopened on the next.
    """
    failures: list[str] = []
    checked = 0
    for step in sorted(match.steps):
        ceremony = match.steps[step]
        if ceremony.theirs is None:
            continue
        checked += 1
        opened, nonce = ceremony.revealed_theirs, disclosed.nonces.get(step)
        if opened is None:
            failures.append(f"step {step}: committed but never revealed")
            continue
        if nonce is None:
            failures.append(f"step {step}: committed but no nonce disclosed")
            continue
        if step not in sealed_states:
            failures.append(f"step {step}: no board state to re-derive against")
            continue
        record = step_record(
            sealed_states[step],
            opened.sender,
            opened.move,
            opened.intent,
            opened.hint,
            barrier_placed=(
                (opened.barrier_placed[0], opened.barrier_placed[1])
                if opened.barrier_placed
                else None
            ),
            scent=opened.scent,
        )
        if not verify_step(record, nonce, ceremony.theirs.commit):
            failures.append(
                f"step {step}: committed {ceremony.theirs.commit[:16]}… but the revealed "
                f"move {opened.move!r} under the disclosed nonce produces "
                f"{commit_of(record, nonce)[:16]}…"
            )
    return AuditResult(
        verdict=Verdict.FORGED if failures else Verdict.CLEAN,
        checked=checked,
        failures=tuple(failures),
    )
