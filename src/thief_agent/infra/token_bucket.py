"""Gate two: the token bucket, and the queue in front of it.

The rulebook's formula, verbatim (FR-7.19)::

    tokens ← min(C, tokens + r·Δt),      allow ⟺ tokens ≥ 1

``C`` is the burst capacity, ``r`` the steady refill rate. The sentence worth
keeping from the book is that **silence is rewarded with future burst capacity**:
an agent that has been quiet accumulates tokens up to ``C`` and may then spend
them at once, which is exactly right for something that reports at the end of a
match rather than continuously.

**These are rate tokens.** The rulebook warns that three unrelated things in this
project are called "token" and must not be confused — rate tokens here, LLM
tokens in :mod:`.token_ledger`, OAuth tokens in :mod:`.token_store`. Nothing in
this module has anything to do with either of the others.

**Refill is computed, not ticked.** There is no background thread and no timer.
``tokens`` is derived from the elapsed time since the last update every time
somebody asks, which means the bucket behaves identically whether the process
was busy, idle, or stopped for an hour — and it means a test can drive a decade
of behaviour through a fake clock in microseconds.

The Appendix F values (30 rpm, 2 concurrent, 5 s backoff, 3 retries, queue 100)
are **minimums**, so this reads them through :func:`~..shared.appendix_f.book_value`
and refuses to be configured *below* them. A parameter marked minimum that drifts
downward is a deviation the audit catches; one that drifts upward is allowed and
sometimes sensible.

A monotonic clock is used rather than the wall clock. A wall clock that steps
backwards — NTP correction, a laptop resuming from sleep — would compute a
negative Δt and, with a naive implementation, either stall the bucket until real
time caught up or refill it wildly. Neither is a thing to debug during a match.
"""

from dataclasses import dataclass, field

from .token_bucket_core import (
    CONCURRENT_REQUESTS,
    MAX_RETRIES,
    QUEUE_DEPTH,
    REQUESTS_PER_MINUTE,
    RETRY_BACKOFF_SEC,
    SECTION,
    QueueFull,
    RateLimitError,
    TokenBucket,
)

__all__ = [
    "CONCURRENT_REQUESTS",
    "MAX_RETRIES",
    "QUEUE_DEPTH",
    "REQUESTS_PER_MINUTE",
    "RETRY_BACKOFF_SEC",
    "SECTION",
    "Limiter",
    "QueueFull",
    "RateLimitError",
    "TokenBucket",
]


@dataclass
class Limiter:
    """The bucket plus the bounded queue the rulebook asks for.

    ``queue_depth`` is where backpressure lives. A limiter with an unbounded
    queue does not limit anything — it converts a rate problem into a memory
    problem and hides it until the process dies, which is strictly worse than
    refusing early because the refusal at least names what happened.
    """

    bucket: TokenBucket = field(default_factory=TokenBucket)
    queue_depth: int = QUEUE_DEPTH
    max_retries: int = MAX_RETRIES
    backoff_sec: float = float(RETRY_BACKOFF_SEC)
    waiting: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        for name, value, floor in (
            ("queue_depth", self.queue_depth, QUEUE_DEPTH),
            ("max_retries", self.max_retries, MAX_RETRIES),
            ("retry_backoff_sec", self.backoff_sec, RETRY_BACKOFF_SEC),
        ):
            if value < floor:
                raise RateLimitError(
                    f"{name} is a minimum in Appendix F ({floor}); {value} is below it"
                )

    def enter(self) -> float:
        """Join the queue. Returns the seconds to wait before sending.

        Raises:
            QueueFull: when the queue is at capacity. This is the limiter
                working, not failing — a caller that cannot be admitted should
                be told now rather than after it has waited.
        """
        if self.waiting >= self.queue_depth:
            raise QueueFull(
                f"{self.waiting} requests already waiting, queue depth is {self.queue_depth}; "
                "refusing rather than growing, because an unbounded queue turns a rate "
                "problem into a memory problem and hides it until the process dies"
            )
        delay = self.bucket.wait_for()
        if delay == 0.0:
            self.bucket.allow()
            return 0.0
        self.waiting += 1
        return delay

    def leave(self) -> None:
        """Release a queued slot once the caller has stopped waiting."""
        self.waiting = max(self.waiting - 1, 0)

    def backoff_for(self, attempt: int) -> float:
        """Seconds to wait before retry number ``attempt`` (1-based).

        Exponential from the configured base, so a service that is genuinely
        overloaded is not asked again on the same cadence that overloaded it.

        Raises:
            RateLimitError: once ``max_retries`` is exhausted. Named rather
                than returning a sentinel, because "retry forever" is the
                behaviour FR-7.22 says can get an account suspended.
        """
        if attempt < 1:
            raise RateLimitError(f"attempts are numbered from 1, got {attempt}")
        if attempt > self.max_retries:
            raise RateLimitError(
                f"{self.max_retries} retries exhausted; there is no further attempt, "
                "because insisting is what gets an account suspended"
            )
        return self.backoff_sec * (2.0 ** (attempt - 1))
