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
import contextlib
import threading
from dataclasses import dataclass, field
from typing import Any

from fastmcp import Client

HTTP_CLIENT_MODULES = frozenset({"httpx", "httpcore"})
"""Libraries whose exceptions mean *the request never completed*.

``httpx.ConnectError`` is not an ``OSError``, not a ``RuntimeError``, and
carries no response — so it matched nothing in the retry vocabulary and
propagated raw out of a turn. That is the third variant of one mistake: the
retry budget classifies by exception type, and every layer between us and the
socket invents its own hierarchy. Rather than enumerate their classes, treat
*any* exception from the HTTP client that is not an HTTP status as what it is:
the request did not get through.
"""

UPSTREAM_DEAD = frozenset({502, 503, 504})
"""Statuses that mean *the proxy is fine, the peer behind it is not*.

Bad Gateway, Service Unavailable, Gateway Timeout. Deliberately not 4xx: a 404
or a 401 comes from something that answered, and retrying it three times before
declaring the opponent unreachable would report the wrong failure.
"""


def from_http_client(error: BaseException) -> bool:
    """Whether this came from the HTTP client rather than from our own code.

    Checked by module rather than by class for the reason the status is read by
    shape: the classes change between releases, and the first symptom of that
    here would be a match lost to an unhandled exception mid-turn.
    """
    return type(error).__module__.split(".")[0] in HTTP_CLIENT_MODULES


def why(error: BaseException) -> str:
    """The most specific text in the chain, for exceptions that often have none.

    ``httpx.ConnectError`` is routinely raised with an empty message, and its
    ``__cause__`` is frequently another empty one. Walking to the first thing
    that actually says something is the difference between a report and a
    class name.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        said = str(current).strip()
        if said:
            return f"{said} ({type(current).__name__})"
        current = current.__cause__ or current.__context__
    return f"{type(error).__name__} with no detail"


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


SHUTDOWN_GRACE = 5.0
"""Extra seconds allowed for a call to come back before we stop waiting on it.

The inner ``call_tool`` enforces the real deadline. This is only so a wedged
event loop cannot hang the match forever, which is a different failure from a
slow opponent and should not be reported as one.
"""


@dataclass
class FastMcpTransport:
    """Calls tools on the opponent's server over **one** kept-open session.

    Satisfies :class:`~.mcp_client.Transport` structurally. Not declared as
    implementing it, because the Protocol exists precisely so this class is not
    the only thing that can.

    **Why this holds state.** The obvious implementation — ``asyncio.run`` with
    ``async with Client(url)`` per call — is what this was, and it opens a fresh
    event loop, a fresh MCP session and a fresh TLS handshake for every tool
    call. A 35-step sub-game makes a few hundred of them.

    On loopback that is merely wasteful. Through a tunnel it is fatal: free
    tunnels cap new connections, and four consecutive live matches died partway
    through a sub-game — as ``502``, as ``ConnectError``, and finally as a
    failed ``start_tls`` — because the ceremony was opening connections faster
    than the tunnel would grant them. Translating those exceptions made the
    failures legible; only opening fewer connections makes them stop.

    So one session is opened on the first call and kept. The event loop lives in
    a daemon thread, because a session cannot outlive ``asyncio.run``.

    **A session that has failed is not reused.** Anything other than a protocol
    violation drops it, so the next call reconnects. That keeps a half-closed
    connection from turning one network blip into a match-ending run of
    failures, which is exactly what a kept session would otherwise risk.
    """

    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _client: Any = field(default=None, init=False, repr=False)
    _connected_to: str = field(default="", init=False, repr=False)

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        """One tool call on the shared session, opening it if this is the first.

        Args:
            url: the opponent's MCP endpoint, already normalised upstream. A
                different one than last time reconnects — tunnels rotate, and
                the re-handshake exists because that happens.
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
        try:
            answer = asyncio.run_coroutine_threadsafe(
                self._call(url, tool, payload, timeout), self._running_loop()
            ).result(timeout + SHUTDOWN_GRACE)
        except TypeError:
            raise  # their tool answered badly; the connection is fine
        except BaseException:
            self.drop()
            raise
        return answer

    def drop(self) -> None:
        """Forget the session without disturbing the loop. Best effort by design.

        Called after any failure that is not a protocol violation. Closing a
        connection that has already failed can itself fail, and that must not
        replace the original error — the reason the run was ending in the first
        place is worth more than the tidiness of the socket.
        """
        client, self._client, self._connected_to = self._client, None, ""
        loop = self._loop
        if client is None or loop is None or loop.is_closed():
            return
        with contextlib.suppress(Exception):  # see the docstring
            asyncio.run_coroutine_threadsafe(client.__aexit__(None, None, None), loop).result(
                SHUTDOWN_GRACE
            )

    def close(self) -> None:
        """Drop the session and stop the loop. Safe to call twice."""
        self.drop()
        loop, self._loop, thread, self._thread = self._loop, None, self._thread, None
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=SHUTDOWN_GRACE)

    def _running_loop(self) -> asyncio.AbstractEventLoop:
        """The loop the session lives on, started once, in a daemon thread.

        Daemon because a match that has finished should not be held open by a
        thread waiting for work that will never arrive, and :meth:`close` is a
        courtesy rather than something the process depends on.
        """
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._loop.run_forever, name="mcp-client", daemon=True
            )
            self._thread.start()
        return self._loop

    async def _session(self, url: str) -> Any:  # noqa: ANN401 - whatever FastMCP returns
        """The open client for ``url``, reconnecting only when it is not that."""
        if self._client is not None and self._connected_to == url:
            return self._client
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
        client = Client(url)
        # FastMCP's Client is untyped; ignored here rather than relaxing the rule
        # for a module that also holds the failure classification.
        self._client = await client.__aenter__()  # type: ignore[no-untyped-call]
        self._connected_to = url
        return self._client

    async def _call(
        self, url: str, tool: str, payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        try:
            client = await self._session(url)
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
            if from_http_client(exc):
                raise ConnectionError(
                    f"could not reach {url}: {why(exc)}. The request never completed, "
                    "so either the tunnel is no longer forwarding — free tunnels expire "
                    "and their addresses change on restart — or the opponent's agent has "
                    "stopped"
                ) from exc
            raise
        data = answer.data
        if not isinstance(data, dict):
            raise TypeError(
                f"{tool} at {url} returned {type(data).__name__}, not an object; every "
                "tool in this protocol answers with a mapping, and a peer that does not "
                "is not speaking it"
            )
        return data
