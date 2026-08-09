"""The mailbox state: the queues, the ledgers, and the binding at the door.

Split out of :mod:`.inboxes`. :class:`~.inboxes.PeerInboxes` inherits this
class, so every field and method below is a real, typed attribute of it rather
than something attached after the fact.
"""

import queue
from dataclasses import dataclass, field
from typing import Any

from .protocol import AuditPayload, ControlMessage, TurnMessage


@dataclass
class InboxState:
    """The queues, ledgers and binding a :class:`~.inboxes.PeerInboxes` is made of."""

    agreements: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    """Greetings only. Digests go to :attr:`digests`; see :meth:`negotiate`."""

    digests: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    """Config digests, kept apart from greetings even though one tool carries both.

    ``negotiate`` is the protocol's single negotiation channel and it carries
    two unrelated messages: *here is where I am* and *here is the digest of the
    parameters I am playing by*. Draining both into one mailbox meant
    ``latest_agreement`` — which takes the newest item, correctly, because a
    newer greeting supersedes an older one — could hand a digest to
    ``accept_greeting``, which then failed with ``greeting must be an object,
    got NoneType``. Whether it did depended on the order two peers happened to
    call each other in.
    """
    scent_locks: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    """Pre-series scent-model offers, kept apart from greetings and digests.

    A third mailbox rather than a flag on the second, for the reason the second
    exists: ``latest_agreement`` takes the *newest* item because a newer
    greeting supersedes an older one, and every message sharing that queue
    inherits a rule written for greetings. The config gate and the scent gate
    also run one after the other, so an offer that arrived early has to survive
    untouched while the digest gate drains its own queue.
    """

    turns: "queue.Queue[TurnMessage]" = field(default_factory=queue.Queue)
    audits: "queue.Queue[AuditPayload]" = field(default_factory=queue.Queue)
    controls: "queue.Queue[ControlMessage]" = field(default_factory=queue.Queue)
    rejected: list[str] = field(default_factory=list)
    accepted_turns: dict[tuple[str, int, str, int], str] = field(default_factory=dict)
    """``(sender, step, game_uid, sub_game) -> digest`` of every turn taken.

    The duplicate detector, keyed by the same canonical binding
    :attr:`accepted_reveals` already uses. Keyed by ``(sender, step)`` alone it
    was ambiguous across sub-games — step 1 recurs in all six — so it had to be
    emptied at every boundary, and *that* was a race rather than a reset: the
    opponent starts pushing a sub-game's messages when **their** thread reaches
    the boundary, not when ours does. A turn accepted a moment before our own
    reset lost its ledger entry, and the reveal that opened it was then refused
    as having no phase-one commitment — a deadlock, because the sender had no
    reason to send it twice. Binding the key removes the reason to ever forget
    an entry, and the series bounds its size.
    """

    accepted_reveals: dict[tuple[str, int, str, int], str] = field(default_factory=dict)
    """``(sender, step, game_uid, sub_game) -> digest`` of every reveal opened."""

    hint_max_words: int = 15

    game_uid: str = ""
    """The series being played, once one is agreed. Empty means none yet."""

    sub_game: int = 0
    """How far along that series we are. Only messages *behind* it are stale."""

    duplicates: list[str] = field(default_factory=list)
    """Turns dropped as re-sends. Not errors — evidence a retry behaved."""

    deferred: list[str] = field(default_factory=list)
    """Messages refused only because the door was not open for them yet.

    Kept apart from :attr:`rejected`, which is the record a dispute reads: a
    deferral accuses the sender of nothing, and filing it as a refusal would
    make an ordinary boundary race look like a peer breaking the protocol. It is
    still recorded, because a series that spent its retry budget getting in
    needs to show why.
    """

    def bind(self, game_uid: str, sub_game: int) -> None:
        """Open this mailbox for exactly one sub-game of exactly one series.

        Called where the *next* thing we do is tell the opponent we are ready —
        the agreement that opens the series, and the re-greeting that opens each
        later sub-game. Both are messages they wait for before sending anything
        of their own, so binding first is what makes the retryable refusal below
        a safety net rather than the mechanism: an honest peer's opening packet
        arrives at a door that is already open.

        **The series is widened before the sub-game is narrowed, deliberately.**
        These are two separate stores and the door is read on the server thread,
        so a message can land between them. Taking the series first means the
        worst it can see is a door still pointing at the sub-game we just left,
        which *defers* the sender; taking the sub-game first would briefly point
        at a series we are not in, which refuses it for good.
        """
        self.game_uid = game_uid
        self.sub_game = sub_game

    def _refuse(self, what: str, exc: ValueError) -> dict[str, Any]:
        """Record a refusal without raising across the wire.

        Kept rather than discarded: a match that ends in a dispute needs to
        show what arrived and why it was not acted on.
        """
        self.rejected.append(f"{what}: {exc}")
        return {"ok": False, "detail": str(exc)}

    def _reject(self, what: str, detail: str) -> dict[str, Any]:
        """Refuse something well-formed that we will not act on."""
        self.rejected.append(f"{what}: {detail}")
        return {"ok": False, "detail": detail}
