"""The concrete :class:`~.mcp_client.Transport`: a real call to the opponent.

:mod:`.mcp_client` owns the *policy* — deadlines, retries, the frozen payload, the
relocation log — and takes a :class:`~.mcp_client.Transport` it never implements.
This is the implementation, and it is deliberately the dullest module in the
project: open a client, call one tool, return the result.

**The async/sync bridge lives here and nowhere else.** ``fastmcp.Client`` is
asynchronous; :meth:`~.mcp_client.Transport.call` is synchronous by design,
because the retry and deadline logic decides matches and has to be testable
without an event loop. Letting ``async`` leak upward would mean every one of
those tests needed one. So each call runs its own loop, start to finish, and
nothing above this line knows.

That has a cost worth stating: a fresh connection per call, rather than one
session held open for the match. It is the right trade here. Sub-games are
turn-based with seconds between messages, so connection setup is not the
bottleneck — and a long-lived session is exactly the thing that fails silently
when a tunnel restarts between sub-games, which the handshake rotation in
:mod:`.handshake` exists because it *does* happen.

**One translation happens here, and it has to.**
:class:`~.mcp_client.OpponentClient` decides what a failure *means* — what is
retried, when the budget is spent, when a timeout becomes the technical loss
that scores zero for both sides — and it makes that decision by **exception
type**, retrying ``TimeoutError``, ``ConnectionError`` and ``OSError``.

FastMCP throws that distinction away: a peer that is simply not there surfaces
as a bare ``RuntimeError`` reading *"Client failed to connect"*. Passed straight
up, an unreachable opponent would skip the retry budget entirely, never reach
the transport log, and never become the technical loss the rules define — it
would just crash the turn. So a connection failure is re-raised as a
``ConnectionError``, with the original chained.

**Through a tunnel, "not there" is not a connection failure at all.** Locally an
absent peer refuses the connection and the OS raises ``ECONNREFUSED`` — an
``OSError``, already the right vocabulary. Through ngrok the connection
*succeeds*: the tunnel is up and answers ``502`` on the peer's behalf. That
arrives as an HTTP status error, which is neither ``OSError`` nor
``RuntimeError``, so it sailed past every retry in the stack and past
``try_announce``, which only tolerates ``MatchAborted``. The retry logic was
correct and unreachable — it worked in every localhost test and could not work
in the one situation it was written for. So :data:`UPSTREAM_DEAD` statuses are
translated too: a gateway reporting that the thing behind it is not answering
*is* an unreachable opponent, whatever layer says so.

Nothing else is translated. A tool that answers badly answers with a value, and
our own ``TypeError`` below is our own bug; neither is a transport failure and
neither should be retried three times before being reported as an unreachable
opponent.
"""

from fastmcp import Client

from .mcp_transport_failures import (
    HTTP_CLIENT_MODULES,
    UPSTREAM_DEAD,
    from_http_client,
    upstream_status,
    why,
)
from .mcp_transport_loop import SHUTDOWN_GRACE
from .mcp_transport_session import FastMcpTransport

__all__ = [
    "HTTP_CLIENT_MODULES",
    "SHUTDOWN_GRACE",
    "UPSTREAM_DEAD",
    "Client",
    "FastMcpTransport",
    "from_http_client",
    "upstream_status",
    "why",
]
