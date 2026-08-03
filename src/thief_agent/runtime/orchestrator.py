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

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..domain.outcome import TechnicalLoss
from ..infra.inboxes import PeerInboxes
from ..infra.mcp_client import OpponentClient, OpponentUnreachableError
from ..infra.protocol import ROLES
from ..shared.config import config_sha256

PROTOCOL_VERSION = "1.0"
"""Bumped when the wire contract changes. Exchanged during negotiation."""


@dataclass(frozen=True, slots=True)
class MatchAborted(Exception):
    """A subsystem failure ended the sub-game.

    Carries the cause rather than only the fact. Both teams must **agree** a
    result before either may report it, and "technical loss" with no cause is
    far harder to agree on than "timeout at step 12" — so the cause is recorded
    at the point it is known, not reconstructed afterwards.
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

    def check_handshake(self, sender_role: str, protocol_version: str) -> None:
        """Reject a mismatched protocol or a duplicate role before play starts.

        Carried over from the retired tool surface, because both catch
        pre-match errors that otherwise surface mid-turn as arbitrary
        rejections. The duplicate-role case is the sharper one: two peers both
        claiming ``thief`` is a game with no pursuer — nothing to run from,
        no capture possible, and the survival clock running unopposed.

        Raises:
            MatchAborted: with ``TechnicalLoss.ILLEGAL_ACTION``.
        """
        if protocol_version != PROTOCOL_VERSION:
            raise MatchAborted(
                TechnicalLoss.ILLEGAL_ACTION,
                f"protocol {protocol_version} != ours {PROTOCOL_VERSION}",
            )
        if sender_role not in ROLES:
            raise MatchAborted(
                TechnicalLoss.ILLEGAL_ACTION,
                f"unknown role {sender_role!r}; expected one of {sorted(ROLES)}",
            )
        if sender_role == self.role:
            raise MatchAborted(
                TechnicalLoss.ILLEGAL_ACTION, f"both peers claim the role {sender_role!r}"
            )

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
