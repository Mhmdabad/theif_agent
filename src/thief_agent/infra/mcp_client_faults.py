"""The vocabulary of the outbound half: refusals, transport, and failures.

Separated from :mod:`.mcp_client`, which owns the client that raises these and
the loop that decides when. Nothing here knows how many attempts a call gets;
these are the names the rest of the runtime distinguishes a slow opponent from
an unreachable one by.

The names here are re-exported from :mod:`.mcp_client`; importers should keep
using that module rather than reaching in here.
"""

from collections.abc import Mapping
from typing import Any, Protocol

__all__ = [
    "RETRY_KEY",
    "OpponentUnreachableError",
    "PeerNotReadyError",
    "Transport",
    "deferred",
]


RETRY_KEY = "retry"
"""The flag a peer sets on a refusal it wants repeated. See :mod:`.inboxes`.

Duplicated from the door's constant rather than imported, because these two
modules are the two ends of the wire and importing one into the other would say
they are the same program. They are not: this end also has to work against an
opponent whose door is someone else's code.
"""


def deferred(answer: Mapping[str, Any]) -> bool:
    """Whether an answer refused us only for now.

    Both halves must be present. ``ok`` alone is the refusal every peer sends,
    and treating an unflagged one as retryable would spend the whole budget
    re-sending a message the opponent has already judged and refused — turning
    one rejected forgery into four.
    """
    return answer.get("ok") is False and answer.get(RETRY_KEY) is True


class Transport(Protocol):
    """The slice of an MCP client this module depends on.

    A protocol rather than a concrete client so the retry and deadline
    behaviour can be tested without a network. These are the paths that decide
    matches, and they must be exercised deterministically.
    """

    def call(
        self, url: str, tool: str, payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]: ...


class OpponentUnreachableError(RuntimeError):
    """Raised when the opponent could not be reached within the retry budget.

    The caller converts this into a technical loss. It is deliberately not
    retried further up: the budget expressed here *is* the whole allowance.
    """


class PeerNotReadyError(OpponentUnreachableError):
    """Raised when the opponent answered, but never opened its door in time.

    A distinct name because it is a distinct fault — the socket worked and the
    peer refused us for a binding it had not agreed yet — and a subclass because
    the *consequence* is the one thing it shares with a dead tunnel: the budget
    is spent, and every caller that already turns exhaustion into a technical
    loss should turn this into the same one. A peer whose mailbox never opened
    is exactly as unplayable as a peer that never answered.
    """
