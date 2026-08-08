"""All three gates in front of one request, and what a 429 means afterwards.

FR-7.21: a request reaches the API only after passing **all three** gates, and
each fails fast. This module is the order they run in and nothing else — the
gates themselves live in :mod:`.quota`, :mod:`.token_bucket` and
:mod:`.dos_detector`.

The order is not arbitrary. Cheapest and most final first:

1. **DOS detector** — if the pipeline is locked, nothing else matters and no
   state should be spent finding that out.
2. **Quota** — a hard daily ceiling, *checked* here and **reserved** only once
   the request is actually going out. Checking early keeps the fail-fast
   ordering; reserving late is what stops a *wait* from costing a slot. A
   caller that is told to wait has sent nothing, and charging it would let a
   correctly-throttled loop drain the whole day's ceiling without a single
   message leaving — refused, in the end, by the gate that was protecting it.
   The reservation still happens **before the send**, which is the ordering
   that matters: a crash between the call and the response cannot leave an
   uncounted message.
3. **Token bucket** — the only gate that says "not yet" rather than "no". It
   comes before the reservation for the reason above, and after the quota
   *check* because a request that will be refused outright should never have
   waited for a token first.

The 429 rule — why a 429 is never retried immediately, and how one is
recognised at all — lives in :mod:`.gatekeeper_429`.
"""

from dataclasses import dataclass

from .dos_detector import Detector
from .gatekeeper_429 import TOO_MANY_REQUESTS, TooManyRequests, status_code_of
from .quota import Quota
from .token_bucket import Limiter, RateLimitError

__all__ = [
    "TOO_MANY_REQUESTS",
    "Gatekeeper",
    "Rejected",
    "TooManyRequests",
    "Wait",
    "status_code_of",
]


class Rejected(RuntimeError):
    """Raised when a request must not be made. Carries which gate said so."""


@dataclass(frozen=True, slots=True)
class Wait:
    """A request that may proceed, but not yet."""

    seconds: float
    because: str

    def __str__(self) -> str:
        return f"wait {self.seconds:g}s — {self.because}"


@dataclass
class Gatekeeper:
    """The three gates, in order, in front of one request."""

    detector: Detector
    quota: Quota
    limiter: Limiter

    def admit(self) -> Wait | None:
        """Run all three gates. ``None`` means send now.

        Returns:
            ``None`` when the request may go immediately, or a :class:`Wait`
            when the bucket wants time. A wait is not a refusal — the caller
            should sleep and call again.

        Raises:
            Rejected: when a gate refuses outright. The message names the gate,
                because "blocked" without a reason sends somebody to read three
                modules.
        """
        try:
            self.detector.check()
        except Exception as exc:  # noqa: BLE001 - re-raised as one gate error below
            raise Rejected(f"DOS detector: {exc}") from exc

        try:
            self.quota.check()
        except Exception as exc:  # noqa: BLE001
            raise Rejected(f"quota: {exc}") from exc

        try:
            delay = self.limiter.enter()
        except RateLimitError as exc:
            raise Rejected(f"rate limiter: {exc}") from exc
        if delay > 0:
            return Wait(delay, "rate limiter: no token available yet")

        # Reserved only now, once the request is actually going out. Reserving
        # before the bucket ran would charge a slot for every *wait*, and a
        # waiting caller has sent nothing — a loop that is being throttled
        # correctly would drain the whole day's ceiling without a single message
        # leaving, then be refused by the gate that was protecting it.
        try:
            self.quota.reserve()
        except Exception as exc:  # noqa: BLE001
            raise Rejected(f"quota: {exc}") from exc
        return None

    def record_attempt(self) -> None:
        """Tell the DOS detector a send is happening. Called after :meth:`admit`.

        Separate from ``admit`` because the detector must see **attempts**,
        including the ones that fail — and a caller that gave up between being
        admitted and sending never attempted anything.
        """
        self.detector.record()

    def on_429(self, attempt: int, retry_after: float | None = None) -> TooManyRequests:
        """Turn a 429 into a wait, and make the limiter slower for having caused it.

        The provider's ``Retry-After`` wins whenever it is larger than our own
        backoff: it knows about its window and we are guessing. Our backoff wins
        when it is larger, because a provider suggesting one second after we
        have already been refused twice is optimistic on our behalf.

        A token is spent as well. A 429 is the only authoritative signal we ever
        get that our rate limiting was wrong, and a limiter that ignored it
        would keep making the same mistake at the same cadence.

        Returns the exception rather than raising it, so the caller decides
        whether this attempt is the last one.

        Raises:
            RateLimitError: once ``max_retries`` is spent — via
                :meth:`~.token_bucket.Limiter.backoff_for`, which refuses to
                describe an attempt that must not happen.
        """
        ours = self.limiter.backoff_for(attempt)
        self.limiter.bucket.allow()
        return TooManyRequests(max(ours, retry_after or 0.0), attempt)

    def release(self) -> None:
        """Give back a queue slot once the caller has stopped waiting."""
        self.limiter.leave()
