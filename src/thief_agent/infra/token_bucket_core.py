"""The bucket itself, and the Appendix F floors every limit is measured against.

Separated from :mod:`.token_bucket`, which owns the queue and the retry budget
built on top. Nothing here knows that a queue exists: given a clock it answers
only *may this go now, and if not, when*, which is the part the rulebook's
formula is asserted against.

The names here are re-exported from :mod:`.token_bucket`; importers should keep
using that module rather than reaching in here.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..shared.appendix_f import book_value

__all__ = [
    "CONCURRENT_REQUESTS",
    "MAX_RETRIES",
    "QUEUE_DEPTH",
    "REQUESTS_PER_MINUTE",
    "RETRY_BACKOFF_SEC",
    "SECTION",
    "QueueFull",
    "RateLimitError",
    "TokenBucket",
]

SECTION = "rate_limiter_gatekeeper"


def _minimum(key: str) -> int:
    value = book_value(SECTION, key)
    if not isinstance(value, int):  # pragma: no cover - the table is typed
        raise TypeError(f"{SECTION}.{key} is not an integer: {value!r}")
    return value


REQUESTS_PER_MINUTE = _minimum("requests_per_minute")
CONCURRENT_REQUESTS = _minimum("concurrent_requests")
RETRY_BACKOFF_SEC = _minimum("retry_backoff_sec")
MAX_RETRIES = _minimum("max_retries")
QUEUE_DEPTH = _minimum("queue_depth")


class RateLimitError(RuntimeError):
    """Raised when a request cannot proceed under the configured limits."""


class QueueFull(RateLimitError):
    """Raised when the waiting queue is at capacity — backpressure, not an error."""


@dataclass
class TokenBucket:
    """``tokens ← min(C, tokens + r·Δt)``, evaluated on demand.

    Starts **full**. A process that has just started has, by definition, been
    silent, and the book's rule is that silence earns burst capacity. Starting
    empty would also mean the first report of a match waits for no reason.
    """

    capacity: float = float(CONCURRENT_REQUESTS)
    per_minute: float = float(REQUESTS_PER_MINUTE)
    now: Callable[[], float] = field(default=time.monotonic)
    _tokens: float = field(default=-1.0, init=False, repr=False)
    _updated: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.per_minute < REQUESTS_PER_MINUTE:
            raise RateLimitError(
                f"requests_per_minute is a minimum in Appendix F ({REQUESTS_PER_MINUTE}); "
                f"{self.per_minute} is below it, and a *minimum* parameter that drifts "
                "downward is a deviation the audit catches"
            )
        if self.capacity < CONCURRENT_REQUESTS:
            raise RateLimitError(
                f"concurrent_requests is a minimum in Appendix F ({CONCURRENT_REQUESTS}); "
                f"a burst capacity of {self.capacity} is below it"
            )
        self._tokens = self.capacity
        self._updated = self.now()

    @property
    def rate(self) -> float:
        """``r`` — tokens per second."""
        return self.per_minute / 60.0

    def _refill(self) -> None:
        moment = self.now()
        elapsed = max(moment - self._updated, 0.0)
        self._tokens = min(self.capacity, self._tokens + self.rate * elapsed)
        self._updated = moment

    def tokens(self) -> float:
        """How much burst is available right now."""
        self._refill()
        return self._tokens

    def allow(self) -> bool:
        """``allow ⟺ tokens ≥ 1``. Spends a token when it returns ``True``."""
        self._refill()
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    def wait_for(self) -> float:
        """Seconds until one token is available. Zero when a request may go now.

        Returned rather than slept. A module that slept could not be tested
        without a test that also slept, and the caller is better placed to
        decide whether to wait, queue or give up.
        """
        self._refill()
        if self._tokens >= 1.0:
            return 0.0
        return (1.0 - self._tokens) / self.rate
