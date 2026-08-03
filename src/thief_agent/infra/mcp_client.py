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

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


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
        if not self.opponent_url:
            raise ValueError("opponent_url must be set; it is all we know about the opponent")
        if self.response_timeout_sec <= 0:
            raise ValueError(f"response_timeout_sec must be > 0, got {self.response_timeout_sec}")
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")

    @classmethod
    def from_config(cls, network: dict[str, Any]) -> "ClientSettings":
        """Read the opponent URL from the private per-peer config."""
        if "opponent_url" not in network:
            raise ValueError("private config [network] must define opponent_url")
        return cls(opponent_url=str(network["opponent_url"]))


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

    def call(self, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke ``tool`` on the opponent, retrying transport failures only.

        A retry re-sends the **same** payload. It is never a chance to send a
        different move after seeing the opponent's — that is precisely the
        fraud Commit-Reveal exists to prevent, and it is detected at audit.

        Raises:
            OpponentUnreachableError: once the retry budget is spent.
        """
        last: Exception | None = None
        for attempt in range(self._settings.max_retries + 1):
            self.attempts += 1
            try:
                return self._transport.call(
                    self._settings.opponent_url,
                    tool,
                    payload,
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
