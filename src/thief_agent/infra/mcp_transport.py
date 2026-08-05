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

Nothing else is translated. A tool that answers badly answers with a value, and
our own ``TypeError`` below is our own bug; neither is a transport failure and
neither should be retried three times before being reported as an unreachable
opponent.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

from fastmcp import Client


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
        except RuntimeError as exc:
            raise ConnectionError(f"could not reach {url}: {exc}") from exc
        data = answer.data
        if not isinstance(data, dict):
            raise TypeError(
                f"{tool} at {url} returned {type(data).__name__}, not an object; every "
                "tool in this protocol answers with a mapping, and a peer that does not "
                "is not speaking it"
            )
        return data
