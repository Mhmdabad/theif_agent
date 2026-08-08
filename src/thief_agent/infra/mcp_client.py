"""The client half of this peer: calling the opponent's tools.

Each agent is simultaneously server and client. This module owns the outbound
half — everything we know about the opponent is a single URL, and every
statement that arrives through it is untrusted until verified locally.

Deadlines are not optional here. A request without an expiry is the direct
route to deadlock: the main loop waits, the watchdog eventually notices no
heartbeat, and the match dies with no result. Every call therefore carries a
deadline, and a missed deadline is a **failure**, not an invitation to wait
longer.
"""

import dataclasses
import time
from collections.abc import Callable
from typing import Any

from .mcp_client_faults import (
    RETRY_KEY,
    OpponentUnreachableError,
    PeerNotReadyError,
    Transport,
    deferred,
)
from .mcp_client_retry import attempt_series
from .mcp_client_settings import OPPONENT_URL_ENV, ClientSettings
from .transport_log import RECONNECT, SENT, TransportLog

__all__ = [
    "OPPONENT_URL_ENV",
    "RETRY_KEY",
    "ClientSettings",
    "OpponentClient",
    "OpponentUnreachableError",
    "PeerNotReadyError",
    "Transport",
    "deferred",
]


class OpponentClient:
    """Calls the opponent's tools, with a bounded retry budget."""

    def __init__(
        self,
        transport: Transport,
        settings: ClientSettings,
        sleep: Callable[[float], None] | None = None,
        log: TransportLog | None = None,
        on_attempt: Callable[[str], None] = lambda _: None,
    ) -> None:
        self._transport = transport
        self._settings = settings
        self._sleep = time.sleep if sleep is None else sleep
        self.attempts = 0
        self.log = log if log is not None else TransportLog()
        self.on_attempt = on_attempt
        """Liveness hook, fired before every attempt.

        Retrying is not hanging, but from outside they are indistinguishable:
        a call against a dead tunnel can occupy the process for
        :attr:`ClientSettings.worst_case_seconds` — longer than the watchdog's
        patience — and the watchdog would shut the match down mid-recovery,
        turning a clean named timeout into a stall report. Saying "still
        trying" on each attempt is what keeps the two apart.
        """
        self._connected: set[str] = set()

    @property
    def opponent_url(self) -> str:
        """Where calls are going right now. Not necessarily where they started."""
        return self._settings.opponent_url

    @property
    def sent(self) -> list[tuple[str, str]]:
        """``(tool, sha256)`` per call. Evidence that a retry changed nothing.

        Derived from the log rather than kept beside it. Two records of the
        same thing is one record that can be wrong without anyone noticing —
        and this one is the record an opponent may be shown.
        """
        return [(event.tool, event.detail) for event in self.log.of_kind(SENT)]

    @property
    def relocations(self) -> list[tuple[str, str]]:
        """``(was, now)`` per address change, derived from the same log."""
        return [(event.detail, event.url) for event in self.log.of_kind(RECONNECT)]

    def repoint(self, url: str) -> str:
        """Send subsequent calls somewhere else, recording the move.

        A free-tier tunnel issues a new URL on every restart, so the address
        agreed at the start of a series can stop existing partway through.
        Re-pointing beats restarting the series — but it is only ever done
        from an accepted re-handshake, never from a redirect the transport
        happened to follow, and the previous address is kept so a match that
        ends in a dispute can show where its traffic actually went.

        Returns:
            The address that was in force before the move.
        """
        was = self._settings.opponent_url
        self._settings = dataclasses.replace(self._settings, opponent_url=url)
        if self._settings.opponent_url != was:
            self.log.record(RECONNECT, "", self._settings.opponent_url, detail=was)
        return was

    def call(self, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke ``tool`` on the opponent, retrying what is worth retrying.

        **Transport failures, and refusals the peer asked us to repeat.** The
        second kind is the door saying *not yet* — see :func:`deferred` — and it
        spends the same budget for the same reason: the alternative is a
        fire-and-forget sender that loses a sub-game to a boundary its opponent
        crossed a millisecond later. A refusal without that flag is the peer's
        judgement of the message and is returned untouched, so a forgery costs
        one attempt rather than four.

        Exhaustion of either kind is a technical loss rather than a wait: the
        attempts are counted out in advance, so a door that never opens ends the
        call at a moment neither side has to guess.

        **A retry re-sends bytes, not an intention.** The payload is serialised
        canonically once, before the first attempt, and every attempt sends a
        fresh object rebuilt from those exact bytes. Passing the caller's dict
        down the retry loop would have looked identical and been weaker: a
        caller that mutated it between attempts — or a transport that annotated
        it in place — would turn attempt two into a *different action*, which is
        precisely the "change a move after seeing the opponent's" fraud that
        Commit-Reveal exists to prevent and that is detected at audit.

        Freezing here rather than trusting call sites means the guarantee holds
        for call sites that have not been written yet.

        Raises:
            PeerNotReadyError: once the budget is spent against a door that
                kept deferring us.
            OpponentUnreachableError: once it is spent against a dead socket.
            TypeError: if the payload cannot be serialised. Deliberately before
                the first attempt: a message we cannot reproduce byte-for-byte
                is one we cannot prove we sent only once.
        """
        return attempt_series(self, tool, payload)
