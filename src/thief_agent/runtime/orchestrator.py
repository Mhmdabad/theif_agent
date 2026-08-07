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
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.board import BoardState
from ..domain.lock import ScentAgreement, ScentLock, disputes, propose
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
from ..infra.inboxes import DIGEST_KEY, SCENT_DIGEST_KEY, SCENT_KEY, SERIES_KEY, PeerInboxes
from ..infra.mcp_client import OpponentClient, OpponentUnreachableError
from ..shared.config import config_sha256, digests_agree

PROTOCOL_VERSION = "1.0"
"""Bumped when the wire contract changes. Exchanged during negotiation."""

GREETING_TIMEOUT_SEC = 30.0
"""How long to wait for the opponent's address before declaring a timeout.

The Appendix F response timeout. A handshake with no deadline is the one place
a deadlock costs nothing to reach and everything to diagnose: neither peer has
moved, so there is no board state to explain what happened."""

CONFIG_TIMEOUT_SEC = 30.0
"""How long to wait for the opponent's config digest.

The same Appendix F response timeout, for the same reason: nobody has moved
yet, so an unbounded wait here produces a hang with no board to explain it. An
opponent who never answers has not agreed to our parameters, and the only safe
reading of silence at this gate is refusal."""

SCENT_TIMEOUT_SEC = 30.0
"""How long to wait for the opponent's scent-model offer.

The Appendix F response timeout again, and the same reading of silence. A peer
that will not lock the emission model has not agreed to one, and Appendix E rule
23 voids a match played on a model the two sides never fixed — so waiting longer
only delays a series that cannot legitimately open."""


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
        return self.call_opponent("negotiate", {"message": {"greeting": ours.to_dict()}})

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
        message = self.next_agreement(timeout)
        while True:
            try:
                message = self.inboxes.agreements.get_nowait()
            except queue.Empty:
                return message

    def next_agreement(self, timeout: float) -> dict[str, Any]:
        """The next greeting off the mailbox, or a timeout. Never an unbounded wait.

        Split out from :meth:`latest_agreement` because a boundary reads the
        queue one message at a time — every greeting waiting there has to be a
        legal rotation, not merely the last one — while the opening handshake
        only wants the newest. Both need the same deadline.

        Raises:
            MatchAborted: ``TIMEOUT`` once the window closes. A missed deadline
                is a failure, not a reason to wait.
        """
        try:
            return self.inboxes.agreements.get(timeout=timeout)
        except queue.Empty:
            raise MatchAborted(
                TechnicalLoss.TIMEOUT, f"no greeting from the opponent within {timeout}s"
            ) from None

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
        refuses any change that does not follow a sub-game boundary. Every
        greeting waiting in the mailbox is checked, not merely the newest; see
        :meth:`accept_rotation`.

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
        later = self.accept_rotation(current, ours, sub_game, timeout)
        self.adopt(later.theirs)
        if not announced:
            self.announce(ours)
        for role, (was, now) in sorted(current.relocations(later).items()):
            self.beat(f"agreed-move:{role}:{was}->{now}")
        record(directory, game_id, AddressBook.peered(later))
        return later

    def accept_rotation(
        self, current: Peering, ours: Greeting, sub_game: int, timeout: float
    ) -> Peering:
        """The addresses for ``sub_game``, from **every** greeting queued for it.

        :meth:`latest_agreement` takes the newest greeting and discards the rest,
        which is right when the only question is *where is the opponent now* —
        an older address is superseded by definition. At a boundary that is not
        the only question. A rotation is legal only if nothing but the address
        moved, and a greeting that moved something else is precisely the one
        that must not be superseded away by whatever arrived after it.

        Duplicates are still ordinary and still accepted: a retry re-sends the
        same bytes, and refusing that would lose a series to a re-send. What is
        refused is a *contradiction* — two greetings in one window that cannot
        both be the same peer — whichever order they arrived in. That is the
        rule the config and scent gates already apply, for the same reason.

        Raises:
            MatchAborted: ``TIMEOUT`` if nothing arrives inside the window,
                ``ILLEGAL_ACTION`` if any greeting waiting there is not a
                rotation of the peering already agreed.
        """
        self.beat("accept_rotation")
        later = self.rotation(current, ours, self.next_agreement(timeout), sub_game)
        while True:
            try:
                queued = self.inboxes.agreements.get_nowait()
            except queue.Empty:
                return later
            later = self.rotation(current, ours, queued, sub_game)

    def rotation(
        self, current: Peering, ours: Greeting, message: dict[str, Any], sub_game: int
    ) -> Peering:
        """One queued greeting, read as the addresses in force for ``sub_game``.

        Both checks live in :meth:`Peering.rotate` — that nothing but the address
        moved, and that the pair can still play each other at all. Repeating
        either here would be a second validator that can disagree with the first.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` if this is not a rotation of the
                peering already agreed.
        """
        try:
            return current.rotate(ours, Greeting.from_dict(message.get("greeting")), sub_game)
        except HandshakeError as exc:
            raise MatchAborted(TechnicalLoss.ILLEGAL_ACTION, str(exc)) from exc

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

    def agree_config(
        self,
        config: dict[str, Any],
        game_uid: str = "",
        timeout: float = CONFIG_TIMEOUT_SEC,
    ) -> str:
        """Exchange config digests, refusing to play unless both sides agree.

        The digest is computed from the **loaded** configuration rather than
        re-hashed from a file, so the value advertised is provably the one this
        peer is enforcing. Advertising a digest we are not playing by would be
        indistinguishable from cheating at audit.

        **Both halves are required, and only one of them used to be here.**
        Pushing our digest and reading the opponent's ``ok`` proves nothing:
        ``negotiate`` acknowledges any well-formed message, so that ``ok`` is
        the same whether they compared our parameters or never looked at them.
        Agreement is decided the other way round — by taking the digest *they*
        pushed at us and comparing it with ours.

        **Speak, then listen.** Both peers run this at the same time and each
        blocks on a message only the other can send, so a version that waited
        before announcing would be two polite peers deadlocking — the failure
        :meth:`open_series` is ordered to avoid, for the same reason.

        Args:
            game_uid: the series this digest is about, carried so an agreement
                reached for one series cannot be replayed to open another. Sent
                only when set, and enforced only when the opponent sends one
                back: the reference protocol carries the digest alone, and
                refusing a peer for speaking it would lose a match over a field
                the rulebook never asked for.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` if the opponent's digest disagrees
                with ours, ``TIMEOUT`` if none arrives inside the window.
        """
        ours = config_sha256(config)
        self.beat("negotiate_config")
        message: dict[str, object] = {DIGEST_KEY: ours}
        if game_uid:
            message[SERIES_KEY] = game_uid
        reply = self.call_opponent("negotiate", {"message": message})
        if not reply.get("ok", False):
            raise MatchAborted(TechnicalLoss.ILLEGAL_ACTION, str(reply.get("detail", "")))
        self.accept_config_digest(ours, game_uid, timeout)
        return ours

    def accept_config_digest(self, ours: str, game_uid: str, timeout: float) -> str:
        """Consume the opponent's digest and refuse anything short of agreement.

        **Every** digest queued for this series has to agree, not merely the
        first. A retry re-sends the same bytes, so duplicates are ordinary and
        expected — but stopping at the first one would let a re-send that
        arrived before a contradiction stand in for the contradiction, which is
        the one arrangement of messages where a peer changing its parameters
        mid-negotiation would go unnoticed.

        Digests naming a **different** series are dropped as stale and the wait
        continues on the same deadline, so replaying an agreement from an
        earlier series buys nothing and does not shorten our patience either.

        Consumed rather than peeked, so nothing is left in the mailbox that
        could open the *next* series without a negotiation of its own.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` on disagreement, ``TIMEOUT`` if
                nothing about this series arrives before the deadline.
        """
        self.beat("await_config")
        deadline = time.monotonic() + timeout
        agreed: str | None = None
        while agreed is None:
            agreed = self.check_digest(self.wait_for_digest(deadline, timeout), ours, game_uid)
        while True:
            try:
                queued = self.inboxes.digests.get_nowait()
            except queue.Empty:
                return agreed
            self.check_digest(queued, ours, game_uid)

    def wait_for_digest(self, deadline: float, timeout: float) -> dict[str, Any]:
        """The next digest message, or a timeout. Never an unbounded wait.

        Raises:
            MatchAborted: ``TIMEOUT`` once the deadline passes. Silence at this
                gate is a refusal to agree, not a reason to wait longer.
        """
        try:
            return self.inboxes.digests.get(timeout=max(deadline - time.monotonic(), 0.0))
        except queue.Empty:
            raise MatchAborted(
                TechnicalLoss.TIMEOUT,
                f"no config digest from the opponent within {timeout:g}s; an "
                "unanswered agreement is a refusal to agree, and a series played "
                "without one is void either way",
            ) from None

    def check_digest(self, body: dict[str, Any], ours: str, game_uid: str) -> str | None:
        """Their digest from one message, or ``None`` if it is not about this series.

        Compared in constant time through :func:`~..shared.config.digests_agree`,
        against the canonical lowercase form :func:`require_digest` normalises to
        at the door — so this only ever compares two values of the same shape.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` if their parameters are not ours.
        """
        theirs = str(body.get(DIGEST_KEY, ""))
        about = str(body.get(SERIES_KEY, ""))
        if game_uid and about and about != game_uid:
            self.beat(f"stale-digest:{about}")
            return None
        if not digests_agree(ours, theirs):
            raise MatchAborted(
                TechnicalLoss.ILLEGAL_ACTION,
                f"the opponent is playing by {theirs} and we are playing by {ours}; "
                "Appendix E rule 11 requires byte-identical configuration on both "
                "sides, and a series played on two sets of physics produces two "
                "logs nobody can reconcile — zero for both teams",
            )
        return theirs

    def agree_scent_model(
        self,
        game_uid: str,
        ours: ScentLock | None = None,
        timeout: float = SCENT_TIMEOUT_SEC,
    ) -> ScentAgreement:
        """Exchange the scent-emission model, refusing to play unless it is shared.

        Appendix E rule 23: the model is locked cryptographically **before** the
        game starts, and a deviation in the decay formula voids the match. The
        lock existed and was never sent — ``domain/lock.py`` had no import site
        in ``src/`` at all — so the two known divergences from the reference
        implementation surfaced as an audit failure halfway through a series
        instead of as a conversation before it opened.

        The offer is built from the **live engine** through
        :func:`~..domain.lock.propose`, never transcribed, so what we hash is
        what we will actually emit. Whatever it says, it says only about the
        published 5x5 worked example: no nonce exists yet, no commitment has
        been made, and the live board is not an input, so nothing about our
        position can travel in it.

        **Speak, then listen**, exactly as :meth:`agree_config` does and for the
        same reason: both peers run this at once and each blocks on a message
        only the other can send.

        Args:
            game_uid: the series this lock is about. Required rather than
                optional — unlike the config digest, this message is our dialect
                and not the reference's, so a peer sending one at all can bind
                it. An empty value is refused by the opponent's own door, which
                is where we would rather learn about it than at their audit.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` if their model is not ours or their
                offer was refused, ``TIMEOUT`` if none arrives inside the window.
        """
        ours = ours or propose()
        self.beat("negotiate_scent")
        reply = self.call_opponent("negotiate", {"message": self.scent_offer(ours, game_uid)})
        if not reply.get("ok", False):
            raise MatchAborted(TechnicalLoss.ILLEGAL_ACTION, str(reply.get("detail", "")))
        return self.accept_scent_lock(ours, game_uid, timeout)

    @staticmethod
    def scent_offer(ours: ScentLock, game_uid: str) -> dict[str, object]:
        """The canonical offer: the model, its digest, and the series it binds."""
        return {SCENT_KEY: ours.terms(), SCENT_DIGEST_KEY: ours.digest(), SERIES_KEY: game_uid}

    def accept_scent_lock(self, ours: ScentLock, game_uid: str, timeout: float) -> ScentAgreement:
        """Consume the opponent's offers and refuse anything short of agreement.

        **Every** offer queued for this series has to agree, not merely the
        first, for the reason the config gate already gives: a retry re-sends
        the same bytes, so duplicates are ordinary — but stopping at the first
        would let a re-send stand in for a contradiction queued behind it, which
        is the one arrangement of messages where a peer changing its model
        mid-negotiation goes unnoticed.

        Offers naming a **different** series are dropped as stale and the wait
        continues on the same deadline. Consumed rather than peeked, so nothing
        is left behind that could open the *next* series unlocked.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` on disagreement, ``TIMEOUT`` if
                nothing about this series arrives before the deadline.
        """
        self.beat("await_scent")
        deadline = time.monotonic() + timeout
        settled: ScentAgreement | None = None
        while settled is None:
            settled = self.check_scent_lock(
                self.wait_for_scent_lock(deadline, timeout), ours, game_uid
            )
        while True:
            try:
                queued = self.inboxes.scent_locks.get_nowait()
            except queue.Empty:
                return settled
            self.check_scent_lock(queued, ours, game_uid)

    def wait_for_scent_lock(self, deadline: float, timeout: float) -> dict[str, Any]:
        """The next offer, or a timeout. Never an unbounded wait.

        Raises:
            MatchAborted: ``TIMEOUT`` once the deadline passes. A peer that
                offers no model has not agreed one, and Appendix E rule 23 voids
                a match played on a model nobody fixed.
        """
        try:
            return self.inboxes.scent_locks.get(timeout=max(deadline - time.monotonic(), 0.0))
        except queue.Empty:
            raise MatchAborted(
                TechnicalLoss.TIMEOUT,
                f"no scent-model lock from the opponent within {timeout:g}s; Appendix E "
                "rule 23 fixes the emission model before the game starts, and a peer "
                "that will not lock one cannot produce a heatmap either side can check",
            ) from None

    def check_scent_lock(
        self, body: dict[str, Any], ours: ScentLock, game_uid: str
    ) -> ScentAgreement | None:
        """Their offer settled, or ``None`` if it is not about this series.

        Decided by :func:`~..domain.lock.disputes`, which is where the physics
        live: this class coordinates and does not decide, and a second opinion
        about the model here is a second opinion that can disagree with the one
        both repositories share.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` if their model is not ours.
        """
        about = str(body.get(SERIES_KEY, ""))
        if about != game_uid:
            self.beat(f"stale-scent-lock:{about}")
            return None
        offer = body.get(SCENT_KEY)
        problems = disputes(
            ours, offer if isinstance(offer, dict) else {}, str(body.get(SCENT_DIGEST_KEY, ""))
        )
        if problems:
            raise MatchAborted(
                TechnicalLoss.ILLEGAL_ACTION,
                "; ".join(problems) + "; Appendix E rule 23 locks the scent-emission "
                "model before the game starts and prices a deviation in the decay "
                "formula at a void match, so the remedy is negotiation between the "
                "teams rather than a series played on two different fields",
            )
        return ours.agreement()
