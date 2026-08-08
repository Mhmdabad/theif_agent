"""The event loop, the thread it runs on, and the session they keep open.

Split out of :mod:`.mcp_transport`, which re-exports :data:`SHUTDOWN_GRACE`.
A session cannot outlive ``asyncio.run``, so the loop lives in a thread of its
own for as long as the transport does; the state a call reuses, and the care
that tearing it down needs, are both here.
"""

import asyncio
import contextlib
import threading
from dataclasses import dataclass, field
from typing import Any

SHUTDOWN_GRACE = 5.0
"""Extra seconds allowed for a call to come back before we stop waiting on it.

The inner ``call_tool`` enforces the real deadline. This is only so a wedged
event loop cannot hang the match forever, which is a different failure from a
slow opponent and should not be reported as one.
"""


@dataclass
class SessionOnALoop:
    """The loop, the thread, and the one open client a transport reuses.

    Split from :class:`~.mcp_transport.FastMcpTransport`, where the reasoning
    for holding a session at all is written down. This half owns the lifecycle
    only: start the loop once, keep what a later call reuses, and let go of a
    session that has failed without letting the tidying replace the failure.
    """

    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _client: Any = field(default=None, init=False, repr=False)
    _connected_to: str = field(default="", init=False, repr=False)

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
