"""A 429 from the provider: what it means, and how one is recognised.

**429 is not a transient glitch.** FR-7.22 is explicit: insisting and
immediately re-sending can get the account suspended *by the provider*. So a 429
does not enter the ordinary retry path. It is treated as a statement about the
window we are in, honoured with a wait, and — because the provider has just told
us our own rate limiting was wrong — it also **spends a token from the bucket**,
so the next request is further away than it would otherwise have been. A limiter
that ignored the one authoritative signal about its own configuration would keep
making the same mistake politely.

There is deliberately **no path that retries a 429 without waiting**. The wait
comes from ``Retry-After`` when the provider sends one, and from the configured
backoff when it does not; the provider's number wins whenever it is larger,
because it knows about its own window and we are guessing.
"""

from collections.abc import Callable
from dataclasses import dataclass

TOO_MANY_REQUESTS = 429


@dataclass(frozen=True, slots=True)
class TooManyRequests(Exception):
    """The provider said 429. Honoured, never immediately retried."""

    retry_after: float
    attempt: int

    def __str__(self) -> str:
        return (
            f"HTTP 429 on attempt {self.attempt}; waiting {self.retry_after:g}s. "
            "This is not a transient glitch — re-sending immediately is what gets "
            "an account suspended"
        )


def status_code_of(
    error: object, reader: Callable[[object], int | None] | None = None
) -> int | None:
    """Best-effort HTTP status from whatever the client library raised.

    Google's client raises ``HttpError`` carrying ``resp.status``; others use
    ``status_code``, and a bare ``int`` shows up in tests and thin wrappers.
    Reading several shapes here keeps the 429 rule from depending on which
    library happens to be installed — a rule that only fired for one exception
    type would silently stop firing after a dependency upgrade.
    """
    if reader is not None:
        return reader(error)
    if isinstance(error, int):
        return error
    for attribute in ("status_code", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(error, "resp", None)
    status = getattr(response, "status", None)
    return status if isinstance(status, int) else None
