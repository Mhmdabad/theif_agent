"""One tool call on the kept-open session, and what its failure is called.

Split out of :mod:`.mcp_transport`, which re-exports :class:`FastMcpTransport`.
``Client`` is deliberately not bound here: it is read from that module when a
session is opened, so the name a caller can point at a different client is the
one an actual connection goes through.
"""

import asyncio
import contextlib
import json
from dataclasses import dataclass
from typing import Any

from .mcp_transport_failures import UPSTREAM_DEAD, from_http_client, upstream_status, why
from .mcp_transport_loop import SHUTDOWN_GRACE, SessionOnALoop


@dataclass
class FastMcpTransport(SessionOnALoop):
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

    async def _session(self, url: str) -> Any:  # noqa: ANN401 - whatever FastMCP returns
        """The open client for ``url``, reconnecting only when it is not that."""
        if self._client is not None and self._connected_to == url:
            return self._client
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
        # ``Client`` lives on :mod:`.mcp_transport` and is read from there at
        # call time: that module is the one place the client class can be
        # pointed at something else, and binding it here would freeze whatever
        # it was at import. Imported in the method so the modules stay acyclic.
        from . import mcp_transport

        client = mcp_transport.Client(url)
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
        if isinstance(data, str):
            # A non-JSON string falls through unchanged to the TypeError below.
            with contextlib.suppress(ValueError):
                data = json.loads(data)
        if not isinstance(data, dict):
            raise TypeError(
                f"{tool} at {url} returned {type(data).__name__}, not an object; every "
                "tool in this protocol answers with a mapping, and a peer that does not "
                "is not speaking it"
            )
        return data
