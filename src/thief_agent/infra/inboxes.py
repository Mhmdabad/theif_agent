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

So does **binding**, and for a stronger reason. A queue the ceremony drains and
a ledger that decides what counts as a replay are both written by this module
before any consumer sees them, so a packet accepted against a binding we have
not agreed is one we can neither judge nor take back. Nothing enters either
until :meth:`PeerInboxes.bind` has said which sub-game of which series this
mailbox is playing, and after that only messages naming exactly that one do.
A sender that is merely early is told to come back — see :data:`RETRY_KEY` —
rather than acknowledged on a binding nobody has agreed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .inboxes_keys import (
    ACK,
    DIGEST_KEY,
    RESULT_DIGEST_KEY,
    RESULT_KEY,
    RETRY_KEY,
    SCENT_DIGEST_KEY,
    SCENT_KEY,
    SERIES_KEY,
    TOOL_NAMES,
    fingerprint,
)
from .inboxes_turns import TurnInbox

__all__ = [
    "ACK",
    "DIGEST_KEY",
    "RESULT_DIGEST_KEY",
    "RESULT_KEY",
    "RETRY_KEY",
    "SCENT_DIGEST_KEY",
    "SCENT_KEY",
    "SERIES_KEY",
    "TOOL_NAMES",
    "PeerInboxes",
    "ToolHost",
    "fingerprint",
    "register",
]


@dataclass
class PeerInboxes(TurnInbox):
    """Thread-safe mailboxes filled by the MCP tools, drained by the runtime."""


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
