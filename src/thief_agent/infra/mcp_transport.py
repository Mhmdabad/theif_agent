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

import asyncio
from dataclasses import dataclass
from typing import Any

from fastmcp import Client

UPSTREAM_DEAD = frozenset({502, 503, 504})
"""Statuses that mean *the proxy is fine, the peer behind it is not*.

Bad Gateway, Service Unavailable, Gateway Timeout. Deliberately not 4xx: a 404
or a 401 comes from something that answered, and retrying it three times before
declaring the opponent unreachable would report the wrong failure.
"""


def upstream_status(error: object) -> int | None:
    """The HTTP status inside a client library's exception, if there is one.

    Read by shape rather than by importing ``httpx`` and catching its class, for
    the same reason :func:`~.gatekeeper.status_code_of` is: a rule that only
    works with one library stops working silently when a dependency changes
    underneath it, and the first symptom here would be a match lost to an
    unhandled exception in the middle of a turn.
    """
    code = getattr(getattr(error, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


@dataclass(frozen=True, slots=True)
class FastMcpTransport:
    """Calls one tool on the opponent's server and returns what came back.

    Satisfies :class:`~.mcp_client.Transport` structurally. Not declared as
    implementing it, because the Protocol exists precisely so this class is not
    the only thing that can.
    """

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        """One request, one response, one event loop.

        Args:
            url: the opponent's MCP endpoint, already normalised upstream.
            tool: one of the four protocol tool names.
            payload: the arguments, already frozen by the caller so a retry
                re-sends identical bytes rather than a fresh serialisation.
            timeout: seconds. Passed to FastMCP as well as being the caller's
                own budget — a client that ignored it would leave the retry
                logic waiting on a request that had already lost its race.

        Returns:
            The tool's result as a mapping. A tool that returned something
            else is a protocol violation rather than a value to coerce, and it
            is reported as one.
        """
        return asyncio.run(self._call(url, tool, payload, timeout))

    @staticmethod
    async def _call(url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        try:
            async with Client(url) as client:
                answer = await client.call_tool(tool, payload, timeout=timeout)
        except (TimeoutError, ConnectionError, OSError):
            raise  # already the vocabulary the retry budget understands
        except Exception as exc:
            status = upstream_status(exc)
            if status in UPSTREAM_DEAD:
                raise ConnectionError(
                    f"could not reach {url}: the tunnel answered {status}, which means "
                    "it is up but nothing is listening behind it — their agent is not "
                    "running, or their tunnel points at a different port"
                ) from exc
            if isinstance(exc, RuntimeError):
                raise ConnectionError(f"could not reach {url}: {exc}") from exc
            raise
        data = answer.data
        if not isinstance(data, dict):
            raise TypeError(
                f"{tool} at {url} returned {type(data).__name__}, not an object; every "
                "tool in this protocol answers with a mapping, and a peer that does not "
                "is not speaking it"
            )
        return data
