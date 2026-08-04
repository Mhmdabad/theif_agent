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

from ..domain.outcome import TechnicalLoss
from ..infra.handshake import AddressBook, Greeting, HandshakeError, check, record
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
        try:
            message = self.inboxes.agreements.get(timeout=timeout)
        except queue.Empty:
            raise MatchAborted(
                TechnicalLoss.TIMEOUT, f"no greeting from the opponent within {timeout}s"
            ) from None
        try:
            theirs = Greeting.from_dict(message.get("greeting"))
            check(ours, theirs)
        except HandshakeError as exc:
            raise MatchAborted(TechnicalLoss.ILLEGAL_ACTION, str(exc)) from exc
        return theirs

    def exchange_addresses(
        self,
        ours: Greeting,
        directory: Path,
        game_id: str,
        timeout: float = GREETING_TIMEOUT_SEC,
    ) -> AddressBook:
        """Trade addresses and write both into the pre-game declaration.

        Announcing first is deliberate. Waiting for the opponent before saying
        anything is a handshake where two polite peers wait for each other
        forever — the deadlock the state machine exists to make impossible.
        """
        self.announce(ours)
        book = AddressBook.of(ours, self.accept_greeting(ours, timeout))
        record(directory, game_id, book)
        return book

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
