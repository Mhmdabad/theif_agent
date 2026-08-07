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
import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ..shared.config import canonical_bytes
from .transport_log import (
    CONNECT,
    RECONNECT,
    RETRY,
    SENT,
    TIMEOUT,
    UNREACHABLE,
    TransportLog,
)
from .tunnel import normalise

OPPONENT_URL_ENV = "OPPONENT_URL"
"""Overrides ``opponent_url`` in the private TOML. See :meth:`ClientSettings.from_config`."""

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


@dataclass(frozen=True, slots=True)
class ClientSettings:
    """How this peer talks to its opponent.

    Defaults follow Appendix F. ``response_timeout_sec`` is negotiable and
    ``max_retries``/``retry_backoff_sec`` are minimums, so all three are
    parameters rather than constants.
    """

    opponent_url: str
    response_timeout_sec: float = 30.0
    max_retries: int = 3
    retry_backoff_sec: float = 5.0

    def __post_init__(self) -> None:
        if not self.opponent_url.strip():
            raise ValueError("opponent_url must be set; it is all we know about the opponent")
        if self.response_timeout_sec <= 0:
            raise ValueError(f"response_timeout_sec must be > 0, got {self.response_timeout_sec}")
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        object.__setattr__(self, "opponent_url", normalise(self.opponent_url))

    @property
    def worst_case_seconds(self) -> float:
        """Longest one call can take before it gives up.

        Every attempt may burn the full response timeout before failing, and
        every gap between attempts costs the backoff:

            (max_retries + 1) * response_timeout_sec + max_retries * retry_backoff_sec

        At the Appendix F defaults that is ``4 * 30 + 3 * 5 = 135`` seconds —
        **more than twice** ``watchdog_timeout_sec`` of 60. That is not a bug
        in either number; it means a peer waiting out a dead tunnel looks
        identical to a peer that has hung, unless it says otherwise. It does:
        :class:`OpponentClient` reports liveness on every attempt.

        Exposed rather than left implicit because ``max_retries`` is a raisable
        minimum, and raising it moves this number without anyone noticing.
        """
        attempts = self.max_retries + 1
        return attempts * self.response_timeout_sec + self.max_retries * self.retry_backoff_sec

    @classmethod
    def from_config(
        cls, network: dict[str, Any], environ: Mapping[str, str] | None = None
    ) -> "ClientSettings":
        """Read the opponent URL, letting the environment override the file.

        The committed TOML points at ``127.0.0.1`` because that is the local
        development loop. League play points somewhere else, and that address
        is a poor thing to commit twice over: it is **ephemeral**, since a
        free-tier tunnel issues a new one on every restart, and it is **not
        ours** — it belongs to whichever team we drew this round, and a repo
        full of other teams' addresses is a record of nothing.

        So :data:`OPPONENT_URL_ENV` wins when it is set. The file keeps the
        loopback default, which means checking out this repository and running
        the two agents against each other still works with no setup — and a
        match against a real opponent is one exported variable, not an edit
        that has to be reverted before the next commit.
        """
        source = os.environ if environ is None else environ
        override = source.get(OPPONENT_URL_ENV, "").strip()
        if not override and "opponent_url" not in network:
            raise ValueError(
                f"private config [network] must define opponent_url, or set {OPPONENT_URL_ENV}"
            )
        return cls(opponent_url=override or str(network["opponent_url"]))


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
        url = self._settings.opponent_url
        frozen = canonical_bytes(payload)
        self.log.record(SENT, tool, url, detail=hashlib.sha256(frozen).hexdigest())
        last: Exception | None = None
        shut = ""
        for attempt in range(self._settings.max_retries + 1):
            self.attempts += 1
            self.on_attempt(tool)
            try:
                answer = self._transport.call(
                    url, tool, json.loads(frozen), self._settings.response_timeout_sec
                )
            except (TimeoutError, ConnectionError, OSError) as exc:
                last = exc
                self.log.record(TIMEOUT, tool, url, detail=f"{type(exc).__name__}: {exc}")
                self._back_off(attempt, tool, url)
            else:
                if url not in self._connected:
                    self._connected.add(url)
                    self.log.record(CONNECT, tool, url)
                if not deferred(answer):
                    return answer
                shut = str(answer.get("detail", ""))
                self.log.record(TIMEOUT, tool, url, detail=f"deferred: {shut}")
                self._back_off(attempt, tool, url)
        spent = f"{tool} failed after {self._settings.max_retries + 1} attempts against {url}"
        self.log.record(UNREACHABLE, tool, url, detail=shut or str(last))
        if shut:
            raise PeerNotReadyError(f"{spent}; the last answer was {shut!r}")
        raise OpponentUnreachableError(spent) from last

    def _back_off(self, attempt: int, tool: str, url: str) -> None:
        """Wait out the agreed gap before the next attempt, if there is one."""
        if attempt >= self._settings.max_retries:
            return
        self.log.record(
            RETRY,
            tool,
            url,
            detail=(
                f"attempt {attempt + 2} of {self._settings.max_retries + 1} "
                f"after {self._settings.retry_backoff_sec:g}s"
            ),
        )
        self._sleep(self._settings.retry_backoff_sec)
