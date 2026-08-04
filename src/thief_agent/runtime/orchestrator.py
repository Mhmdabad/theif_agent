"""The single gateway to every subsystem.

Appendix E rule 3: the orchestrator is the **only** entry point to the
subsystems, and peripheral modules never reference one another. That is not
architectural taste — a decision module that reaches directly into the MCP
connector cannot be replaced without touching both, and the rulebook grades
the ability to swap one component in isolation.

It **coordinates and does not decide**. No game rule lives here; move choice
belongs to the strategy module, legality to the domain layer, transport to the
connector. What lives here is the wiring between them and the conversion of a
subsystem failure into a recorded outcome.

Inbound traffic goes to :class:`~..infra.inboxes.PeerInboxes`, which is the
surface an opponent actually calls. The orchestrator routes into those
mailboxes; it does not re-validate, because two validators that disagree are
worse than one.
"""

import queue
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.board import BoardState
from ..domain.outcome import TechnicalLoss
from ..infra.ceremony import AuditResult, FinalReveal, MatchCeremony, audit_opponent
from ..infra.handshake import (
    AddressBook,
    Greeting,
    HandshakeError,
    Peering,
    check,
    record,
)
from ..infra.inboxes import PeerInboxes
from ..infra.mcp_client import OpponentClient, OpponentUnreachableError
from ..shared.config import config_sha256

PROTOCOL_VERSION = "1.0"
"""Bumped when the wire contract changes. Exchanged during negotiation."""

GREETING_TIMEOUT_SEC = 30.0
"""How long to wait for the opponent's address before declaring a timeout.

The Appendix F response timeout. A handshake with no deadline is the one place
a deadlock costs nothing to reach and everything to diagnose: neither peer has
moved, so there is no board state to explain what happened."""


@dataclass
class MatchAborted(Exception):
    """A subsystem failure ended the sub-game.

    Carries the cause rather than only the fact. Both teams must **agree** a
    result before either may report it, and "technical loss" with no cause is
    far harder to agree on than "timeout at step 12" — so the cause is recorded
    at the point it is known, not reconstructed afterwards.

    **Neither frozen nor slotted, and both for the same reason.** Python sets
    ``__traceback__`` on an exception as it propagates. ``slots=True`` leaves
    nowhere to put it; ``frozen=True`` generates a ``__setattr__`` that refuses
    it. Either way the interpreter discards the exception mid-flight and raises
    something else in its place — a ``TypeError`` about class identity, or a
    ``FrozenInstanceError`` — so the named cause this class exists to carry is
    precisely what gets destroyed.

    Worse, it only happens when a ``@contextlib.contextmanager`` is somewhere
    in the call path, which is why it survived until an acceptance test used a
    fixture. Immutability here was decorative: ``cause`` and ``detail`` are
    written once at the raise site and read at the catch site. An exception
    that cannot be raised is not a trade worth making.
    """

    cause: TechnicalLoss
    detail: str = ""


@dataclass
class Orchestrator:
    """Coordinates the subsystems behind one entry point."""

    inboxes: PeerInboxes
    client: OpponentClient
    role: str = "thief"
    on_event: Callable[[str], None] = lambda _: None
    heartbeats: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Route the connector's liveness into this orchestrator's heartbeats.

        Appendix E rule 3 makes this the only entry point to the subsystems, so
        it is also the only place that can join them up. Without this, a client
        retrying against a dead tunnel is silent for longer than the watchdog's
        patience, and the watchdog reports a stall over a recovery that was
        working exactly as designed.
        """
        self.client.on_attempt = lambda tool: self.beat(f"attempt:{tool}")

    def beat(self, what: str) -> None:
        """Record liveness so the watchdog can tell stalled from slow."""
        self.heartbeats.append(what)
        self.on_event(what)

    def handle_inbound(self, tool: str, payload: object) -> dict[str, Any]:
        """Route an opponent call into the mailboxes.

        Delegates wholesale: validation lives at the door in ``PeerInboxes``,
        and re-checking here would be a second opinion that can disagree with
        the first.
        """
        self.beat(f"inbound:{tool}")
        handler = {
            "negotiate": self.inboxes.negotiate,
            "receive_turn": self.inboxes.receive_turn,
            "submit_audit": self.inboxes.submit_audit,
            "receive_control": self.inboxes.receive_control,
        }.get(tool)
        if handler is None:
            return {"ok": False, "detail": f"unknown tool {tool!r}"}
        return handler(payload)

    def call_opponent(self, tool: str, payload: dict[str, object]) -> dict[str, Any]:
        """Call the opponent, converting exhaustion into a recorded abort.

        Raises:
            MatchAborted: with ``TechnicalLoss.TIMEOUT`` once the retry budget
                is spent. A missed deadline is a failure, not a reason to wait.
        """
        self.beat(f"outbound:{tool}")
        try:
            return self.client.call(tool, dict(payload))
        except OpponentUnreachableError as exc:
            raise MatchAborted(TechnicalLoss.TIMEOUT, str(exc)) from exc

    def greeting(self, public_url: str, group_id: str) -> Greeting:
        """What we tell the opponent about ourselves.

        The role comes from this orchestrator rather than from an argument, so
        the address we announce and the role we play can never disagree.
        """
        return Greeting(
            role=self.role,
            group_id=group_id,
            public_url=public_url,
            protocol_version=PROTOCOL_VERSION,
        )

    def announce(self, ours: Greeting) -> dict[str, Any]:
        """Push our address to the opponent through ``negotiate``."""
        self.beat("announce")
        return self.call_opponent("negotiate", {"greeting": ours.to_dict()})

    def latest_agreement(self, timeout: float) -> dict[str, Any]:
        """Take the **newest** greeting waiting in the mailbox, not the oldest.

        A greeting states where a peer is *now*, so an older one is superseded
        by definition. Reading the queue in arrival order would mean adopting
        an address the opponent has already left — and greetings genuinely do
        accumulate: a peer whose first announcement failed sends a second, and
        a series re-greets before every sub-game.

        The oldest-first version of this looked correct for four stages because
        nothing announced twice until tunnel rotation arrived.

        Raises:
            MatchAborted: ``TIMEOUT`` if the mailbox is empty when the window
                closes. A missed deadline is a failure, not a reason to wait.
        """
        try:
            message = self.inboxes.agreements.get(timeout=timeout)
        except queue.Empty:
            raise MatchAborted(
                TechnicalLoss.TIMEOUT, f"no greeting from the opponent within {timeout}s"
            ) from None
        while True:
            try:
                message = self.inboxes.agreements.get_nowait()
            except queue.Empty:
                return message

    def try_announce(self, ours: Greeting) -> bool:
        """Announce, tolerating an outbound path that no longer exists.

        Only for the re-handshake, where the address we hold may be the very
        thing that has gone stale. Everywhere else a failed call is a technical
        loss and should stay one — a helper that quietly swallows unreachable
        opponents is the fastest way to turn a lost match into a silent one.

        Returns:
            Whether the announcement actually landed.
        """
        try:
            self.announce(ours)
        except MatchAborted:
            self.beat("announce-failed")
            return False
        return True

    def accept_greeting(self, ours: Greeting, timeout: float = GREETING_TIMEOUT_SEC) -> Greeting:
        """Take the opponent's greeting off the queue and decide if we can play.

        Fire-and-forget, like every other inbound message: their greeting is
        pushed into *our* server and drains from :attr:`PeerInboxes.agreements`
        rather than arriving as the return value of our own call.

        The checks live in :func:`~..infra.handshake.check`, which is the only
        validator of a greeting. Re-checking the role and version here — as an
        earlier ``check_handshake`` did — meant two validators that could
        disagree, and the pair that disagrees is always the pair that matters.

        Raises:
            MatchAborted: ``TIMEOUT`` if no greeting arrives inside the window,
                ``ILLEGAL_ACTION`` if the one that does cannot be played
                against. A missed deadline is a failure, not a reason to wait.
        """
        self.beat("accept_greeting")
        message = self.latest_agreement(timeout)
        try:
            theirs = Greeting.from_dict(message.get("greeting"))
            check(ours, theirs)
        except HandshakeError as exc:
            raise MatchAborted(TechnicalLoss.ILLEGAL_ACTION, str(exc)) from exc
        return theirs

    def open_series(
        self,
        ours: Greeting,
        directory: Path,
        game_id: str,
        timeout: float = GREETING_TIMEOUT_SEC,
    ) -> Peering:
        """Trade addresses and write both into the pre-game declaration.

        Announcing first is deliberate. Waiting for the opponent before saying
        anything is a handshake where two polite peers wait for each other
        forever — the deadlock the state machine exists to make impossible.

        Returns the addresses in force for sub-game 1. Later sub-games go
        through :meth:`rehandshake`, which is the same exchange with the
        additional rule that only the address may have moved.
        """
        self.announce(ours)
        peering = Peering(ours, self.accept_greeting(ours, timeout), sub_game=1)
        self.adopt(peering.theirs)
        record(directory, game_id, AddressBook.peered(peering))
        return peering

    def adopt(self, theirs: Greeting) -> None:
        """Point the client at the address the opponent actually announced.

        ``opponent_url`` in the private config is a **bootstrap** address: it
        is how we reach them the first time, and it is whatever we were told
        out of band. Their greeting is the authoritative statement of where
        they are, and it is the value the declaration records — so calls that
        went somewhere else would contradict the file we both signed.

        Only ever called from an accepted greeting. Following a redirect the
        transport happened to return would be a different thing entirely.
        """
        was = self.client.repoint(theirs.public_url)
        if was != theirs.public_url:
            self.beat(f"relocated:{theirs.role}:{was}->{theirs.public_url}")

    def rehandshake(
        self,
        current: Peering,
        ours: Greeting,
        sub_game: int,
        directory: Path,
        game_id: str,
        timeout: float = GREETING_TIMEOUT_SEC,
    ) -> Peering:
        """Re-agree addresses before a later sub-game, and re-point if they moved.

        Free-tier tunnels issue a new URL on every restart, so a six-sub-game
        series can outlive the tunnel it started on. Losing the series to that
        would be absurd — and expensive, because a technical loss scores zero
        for **both** sides, so a dead tunnel destroys sub-games already won on
        the board.

        Both peers re-greet every sub-game, whether or not anything moved. A
        re-handshake that only happens when we already know something changed
        is a re-handshake that cannot discover the thing it exists to discover:
        the side whose tunnel died is precisely the side that cannot tell us.

        Nothing but the address may move. :meth:`Peering.rotate` refuses a
        greeting that also changes role, team or protocol — that is not a
        rotated tunnel, it is a different peer arriving mid-series — and
        refuses any change that does not follow a sub-game boundary.

        **The first announcement is allowed to fail.** This is the part that
        makes rotation actually survivable, and it is not obvious. If *their*
        tunnel is the one that died, the address we hold is dead with it, so
        announcing before listening would abort on the very failure we are here
        to recover from. But if *our* tunnel is the one that moved, they cannot
        reach us at all and announcing is the only way they ever learn where we
        went — so it cannot simply be dropped either.

        So: announce, tolerating failure; listen; adopt whatever address their
        greeting carries; and announce again if the first attempt never landed.
        Between them the two orders cover both single failures. If **both**
        tunnels rotate at once neither side can reach the other and the
        sub-game is genuinely lost — there is no in-band channel left, and
        pretending otherwise would only replace a clean timeout with a hang.

        Swallowing that first failure is safe only because the wait that
        follows carries its own deadline: an opponent who really has gone
        produces a ``TIMEOUT`` a moment later rather than silence.

        Raises:
            MatchAborted: ``TIMEOUT`` if the opponent never re-greets,
                ``ILLEGAL_ACTION`` if the greeting is not a rotation of the one
                already agreed.
        """
        announced = self.try_announce(ours)
        theirs = self.accept_greeting(ours, timeout)
        try:
            later = current.rotate(ours, theirs, sub_game)
        except HandshakeError as exc:
            raise MatchAborted(TechnicalLoss.ILLEGAL_ACTION, str(exc)) from exc

        self.adopt(later.theirs)
        if not announced:
            self.announce(ours)
        for role, (was, now) in sorted(current.relocations(later).items()):
            self.beat(f"agreed-move:{role}:{was}->{now}")
        record(directory, game_id, AddressBook.peered(later))
        return later

    def audit(
        self,
        match: MatchCeremony,
        disclosed: FinalReveal,
        sealed_states: dict[int, BoardState],
    ) -> AuditResult:
        """Re-derive the opponent's whole match, converting forgery into a result.

        The one verdict in this system that is **unappealable**. Everywhere
        else a failure is a technical loss both teams reconcile; a commitment
        that does not open to the move it was revealed as is proof, not a
        dispute, and the rulebook prices it as disqualification.

        Which is exactly why the failure list travels with the exception rather
        than being summarised away: an accusation this serious has to arrive
        with the arithmetic attached, so the other side can run it.

        Raises:
            MatchAborted: with ``TechnicalLoss.FORGERY`` on any failed step.
        """
        self.beat("audit")
        result = audit_opponent(match, disclosed, sealed_states)
        if not result.clean:
            raise MatchAborted(TechnicalLoss.FORGERY, str(result))
        return result

    def agree_config(self, config: dict[str, Any]) -> str:
        """Exchange config digests, refusing to play on any mismatch.

        The digest is computed from the **loaded** configuration rather than
        re-hashed from a file, so the value advertised is provably the one this
        peer is enforcing. Advertising a digest we are not playing by would be
        indistinguishable from cheating at audit.

        Raises:
            MatchAborted: with ``TechnicalLoss.ILLEGAL_ACTION`` on mismatch.
        """
        ours = config_sha256(config)
        self.beat("negotiate_config")
        reply = self.call_opponent("negotiate", {"config_sha256": ours})
        if not reply.get("ok", False):
            raise MatchAborted(TechnicalLoss.ILLEGAL_ACTION, str(reply.get("detail", "")))
        return ours
