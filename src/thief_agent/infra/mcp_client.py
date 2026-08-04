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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ..shared.config import canonical_bytes
from .tunnel import normalise

OPPONENT_URL_ENV = "OPPONENT_URL"
"""Overrides ``opponent_url`` in the private TOML. See :meth:`ClientSettings.from_config`."""


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
        sleep: Callable[[float], None] = lambda _: None,
    ) -> None:
        self._transport = transport
        self._settings = settings
        self._sleep = sleep
        self.attempts = 0
        self.relocations: list[tuple[str, str]] = []
        self.sent: list[tuple[str, str]] = []
        """``(tool, sha256)`` per call. Evidence that a retry changed nothing."""

    @property
    def opponent_url(self) -> str:
        """Where calls are going right now. Not necessarily where they started."""
        return self._settings.opponent_url

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
            self.relocations.append((was, self._settings.opponent_url))
        return was

    def call(self, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke ``tool`` on the opponent, retrying transport failures only.

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
            OpponentUnreachableError: once the retry budget is spent.
            TypeError: if the payload cannot be serialised. Deliberately before
                the first attempt: a message we cannot reproduce byte-for-byte
                is one we cannot prove we sent only once.
        """
        frozen = canonical_bytes(payload)
        self.sent.append((tool, hashlib.sha256(frozen).hexdigest()))
        last: Exception | None = None
        for attempt in range(self._settings.max_retries + 1):
            self.attempts += 1
            try:
                return self._transport.call(
                    self._settings.opponent_url,
                    tool,
                    json.loads(frozen),
                    self._settings.response_timeout_sec,
                )
            except (TimeoutError, ConnectionError, OSError) as exc:
                last = exc
                if attempt < self._settings.max_retries:
                    self._sleep(self._settings.retry_backoff_sec)
        raise OpponentUnreachableError(
            f"{tool} failed after {self._settings.max_retries + 1} attempts "
            f"against {self._settings.opponent_url}"
        ) from last
