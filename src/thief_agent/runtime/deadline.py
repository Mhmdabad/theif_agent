"""Deadlines on every request.

Appendix E rule 6. A request with no expiry is the direct route to deadlock:
the main loop waits, the watchdog eventually notices no heartbeat, and the
match dies with no result — a technical loss scoring **zero for both sides**.

The rulebook's phrasing is worth keeping: *a missed deadline is a failure, not
an invitation to wait longer*. That is the whole design. This module makes the
remaining budget a value that can be inspected and asserted on, rather than a
timeout buried in a transport call where nothing can reason about it.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

DEFAULT_RESPONSE_TIMEOUT_SEC = 30.0
"""Appendix F. Negotiable, so a parameter rather than a constant."""


class DeadlineExpiredError(TimeoutError):
    """Raised when a deadline has passed.

    Subclasses ``TimeoutError`` so the client's retry logic treats it as the
    transport fault it is, rather than needing a special case.
    """


@dataclass(frozen=True, slots=True)
class Deadline:
    """A point in time by which a request must have completed."""

    expires_at: float
    label: str = ""

    def remaining(self, now: float) -> float:
        """Seconds left, never negative."""
        return max(0.0, self.expires_at - now)

    def expired(self, now: float) -> bool:
        return now >= self.expires_at

    def check(self, now: float) -> None:
        """Raise if the deadline has passed.

        Raises:
            DeadlineExpiredError: naming the label, so a log says which
                request died rather than only that one did.
        """
        if self.expired(now):
            what = self.label or "request"
            raise DeadlineExpiredError(
                f"{what} exceeded its deadline by {now - self.expires_at:.3f}s"
            )


@dataclass
class DeadlineTracker:
    """Issues deadlines and reports on them.

    Time is injected rather than read from the clock directly, so expiry
    behaviour is tested deterministically instead of with sleeps. These are the
    paths that decide matches; they should be the most reliably covered code in
    the system, not the least.
    """

    timeout_sec: float = DEFAULT_RESPONSE_TIMEOUT_SEC
    clock: Callable[[], float] = time.monotonic
    issued: list[Deadline] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.timeout_sec <= 0:
            raise ValueError(f"timeout_sec must be > 0, got {self.timeout_sec}")

    def start(self, label: str = "") -> Deadline:
        """Open a deadline for one request."""
        deadline = Deadline(self.clock() + self.timeout_sec, label)
        self.issued.append(deadline)
        return deadline

    def remaining(self, deadline: Deadline) -> float:
        return deadline.remaining(self.clock())

    def check(self, deadline: Deadline) -> None:
        deadline.check(self.clock())

    def expired_count(self) -> int:
        """How many issued deadlines have passed. Diagnostic, not a gate."""
        now = self.clock()
        return sum(1 for d in self.issued if d.expired(now))
