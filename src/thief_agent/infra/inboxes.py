"""The peer's mailboxes and the four tools that fill them.

The reference model is fire-and-forget: the opponent pushes a message into our
server, the tool enqueues it and returns ``{"ok": True}`` immediately, and our
runtime drains the queue on its own schedule. Replies travel as separate pushes
into *their* server, not as return values.

That decoupling is why a peer can be slow without being stalled — accepting a
message costs nothing, so a busy runtime never makes the opponent's send time
out. It also means an inbound message can never block on our decision-making,
which is where the language-model deadline lives.

Validation happens **at the door**, before anything reaches a queue. A malformed
message is refused and recorded rather than enqueued for a consumer that would
have to handle it mid-turn.
"""

import hashlib
import queue
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..shared.config import canonical_bytes
from .protocol import AuditPayload, ControlMessage, TurnMessage
from .validation import InvalidPayloadError, require_mapping


def fingerprint(turn: TurnMessage) -> str:
    """A digest of everything a turn asserts.

    Canonical serialisation, so two peers hashing the same turn agree — the
    same rule already used for ``config_sha256``. Comparing digests rather than
    objects means a re-send is recognised even after a round trip through JSON,
    where dictionary order and integer/float typing need not survive.
    """
    return hashlib.sha256(canonical_bytes(turn.to_dict())).hexdigest()


ACK: dict[str, Any] = {"ok": True}
"""What every tool returns on acceptance. The reference expects exactly this."""

TOOL_NAMES: tuple[str, ...] = ("negotiate", "receive_turn", "submit_audit", "receive_control")
"""The complete inbound surface, exactly as the reference names it."""


@dataclass
class PeerInboxes:
    """Thread-safe mailboxes filled by the MCP tools, drained by the runtime."""

    agreements: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    turns: "queue.Queue[TurnMessage]" = field(default_factory=queue.Queue)
    audits: "queue.Queue[AuditPayload]" = field(default_factory=queue.Queue)
    controls: "queue.Queue[ControlMessage]" = field(default_factory=queue.Queue)
    rejected: list[str] = field(default_factory=list)
    accepted_turns: dict[tuple[str, int], str] = field(default_factory=dict)
    """``(sender, step) -> digest`` of every turn taken. The duplicate detector."""

    duplicates: list[str] = field(default_factory=list)
    """Turns dropped as re-sends. Not errors — evidence a retry behaved."""

    def _refuse(self, what: str, exc: InvalidPayloadError) -> dict[str, Any]:
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

    def negotiate(self, message: object) -> dict[str, Any]:
        """Receive the opponent's signed game agreement."""
        try:
            self.agreements.put(require_mapping(message, "agreement"))
        except InvalidPayloadError as exc:
            return self._refuse("negotiate", exc)
        return ACK

    def receive_turn(self, message: object) -> dict[str, Any]:
        """Receive the opponent's turn. Receiving one makes it our turn.

        **A re-sent turn is not a second turn.** The sender's retry loop
        guarantees identical bytes go out, but that guarantee is worth nothing
        on its own: a request that timed out *after* being delivered gets
        retried, and without this the same step would be enqueued twice and
        played twice. So a turn already taken for ``(sender, step)`` is
        acknowledged and dropped — acknowledged, because it genuinely did
        arrive, and refusing would only make the sender retry again.

        **The same step arriving with different content is the opposite.** That
        is not a retry; it is a move changed after the fact, the exact fraud
        Commit-Reveal exists to expose. It is refused and recorded, because
        silently keeping the first copy would hide evidence the audit needs.
        """
        try:
            turn = TurnMessage.from_dict(message)
        except InvalidPayloadError as exc:
            return self._refuse("receive_turn", exc)
        key, digest = (turn.sender, turn.step), fingerprint(turn)
        taken = self.accepted_turns.get(key)
        if taken == digest:
            self.duplicates.append(f"receive_turn: {turn.sender} step {turn.step} re-sent")
            return ACK
        if taken is not None:
            return self._reject(
                "receive_turn",
                f"{turn.sender} already played step {turn.step} with a different message; "
                "a retry may re-send an action, never replace one",
            )
        self.accepted_turns[key] = digest
        self.turns.put(turn)
        return ACK

    def submit_audit(self, payload: object) -> dict[str, Any]:
        """Receive the opponent's end-of-game reveal: records and nonces."""
        try:
            self.audits.put(AuditPayload.from_dict(payload))
        except InvalidPayloadError as exc:
            return self._refuse("submit_audit", exc)
        return ACK

    def receive_control(self, message: object) -> dict[str, Any]:
        """Receive a control signal: enable, status, restart or quit."""
        try:
            self.controls.put(ControlMessage.from_dict(message))
        except InvalidPayloadError as exc:
            return self._refuse("receive_control", exc)
        return ACK


class ToolHost(Protocol):
    """The one method of ``FastMCP`` this module needs."""

    def tool(self, fn: Callable[..., dict[str, Any]]) -> object: ...


def register(host: ToolHost, inboxes: PeerInboxes) -> tuple[str, ...]:
    """Expose the four tools on a FastMCP host.

    The parameter names matter as much as the tool names: the reference sends
    ``{"message": ...}`` for three of them and ``{"payload": ...}`` for
    ``submit_audit``. A mismatch there fails at first contact with a real
    opponent, which is the worst moment to discover it.
    """
    host.tool(inboxes.negotiate)
    host.tool(inboxes.receive_turn)
    host.tool(inboxes.submit_audit)
    host.tool(inboxes.receive_control)
    return TOOL_NAMES
