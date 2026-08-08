"""The gateway surface every other orchestrator module is bolted onto.

Separated from :mod:`.orchestrator`, which owns the dataclass this base class
is mixed into. Nothing here is captured: every mixin reads ``self.client``,
``self.inboxes`` and ``self.beat`` at the moment it uses them, never once at
construction. Two of them are rebound while a match is running — ``adopt``
re-points the client when a free tunnel moves, and the watchdog hook is
installed on the client after this object already exists — so a snapshot of
either is an orchestrator that keeps calling a dead address, or a watchdog
that reports a stall over a recovery that is working.

The attribute declarations below are that contract written down: they are
annotations only, so the dataclass fields still live in :mod:`.orchestrator`
and nothing is bound here at import time.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..domain.board import BoardState
from ..domain.outcome import TechnicalLoss
from ..infra.ceremony import AuditResult, FinalReveal, MatchCeremony, audit_opponent
from ..infra.inboxes import PeerInboxes
from ..infra.mcp_client import OpponentClient, OpponentUnreachableError

__all__ = [
    "MatchAborted",
    "OrchestratorCore",
]


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


class OrchestratorCore:
    """Heartbeat, inbound routing, outbound calls and the audit hand-off."""

    inboxes: PeerInboxes
    client: OpponentClient
    role: str
    on_event: Callable[[str], None]
    heartbeats: list[str]

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
