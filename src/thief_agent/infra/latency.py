"""How long the tunnel actually takes, and what that says about the timeouts.

``response_timeout_sec`` is 30 seconds by Appendix F. Picking a number and
hoping is not a justification, and the rulebook asks for the measurement:
round-trip latency has to be recorded and the timeout defended against it.

**What the timeout is actually covering is the whole argument.** The instinct
is to add the opponent's thinking time to the network time and check the sum
fits in 30 seconds — and it does not, because ``step_deadline_seconds`` is 30
on its own, leaving nothing for the network. That arithmetic would say the
configuration is broken.

It is not, because the protocol is **fire-and-forget**. An inbound tool call
validates a message, drops it in a mailbox and returns ``{"ok": True}``. The
opponent's decision-making happens after the response has gone, on their own
clock, and their reply travels as a separate push into our server. So the
response timeout covers *a push and an enqueue* — a network round trip and a
few microseconds of Python — while the opponent's think time is bounded
separately by ``turn_timeout_seconds``.

That is why the decoupling in :mod:`.inboxes` is not merely tidy. If a tool
call blocked while the far side decided its move, every response timeout would
have to exceed every opponent's worst thinking time, and a peer that thought
slowly would time out a peer that was working perfectly.

So the number to measure is the round trip, and the number to compare it
against is 30 seconds — which should turn out to be enormous. Measuring anyway
is the point: a tunnel that has degraded to seconds per call is a fact worth
having *before* the match rather than inferring it from a technical loss
afterwards.

Percentiles are nearest-rank rather than interpolated. With a few dozen samples
an interpolated p95 reports a duration that never happened, and the honest
statement is "95% of calls came back within a time we actually observed".
"""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .mcp_client import Transport

DEFAULT_RESPONSE_TIMEOUT_SEC = 30.0
"""Appendix F. Negotiable **upward**: a minimum may be raised, never lowered."""

COMFORTABLE_HEADROOM = 10.0
"""Ratio of timeout to observed p95 below which the margin is worth reporting.

Ten rather than two. The failure this guards against is not the average call
being slow — it is one call in a match hitting a stall an order of magnitude
past normal, and a technical loss scores zero for **both** sides, so the cost
of a thin margin is a whole sub-game rather than a retry.
"""


@dataclass
class LatencyLog:
    """Observed round-trip times, in seconds, in the order they happened."""

    samples: list[float] = field(default_factory=list)
    by_tool: dict[str, list[float]] = field(default_factory=dict)

    def record(self, tool: str, seconds: float) -> None:
        """Add one observation. Negative durations are a broken clock, not data."""
        if seconds < 0:
            raise ValueError(f"round trip cannot be negative, got {seconds}")
        self.samples.append(seconds)
        self.by_tool.setdefault(tool, []).append(seconds)

    def summary(self) -> "Summary":
        return Summary.of(self.samples)


@dataclass(frozen=True, slots=True)
class Summary:
    """What a set of round trips looked like."""

    count: int
    fastest: float
    median: float
    p95: float
    slowest: float

    @classmethod
    def of(cls, samples: list[float]) -> "Summary":
        """Summarise, or report zeroes for an empty log.

        Zeroes rather than an exception: "we have not measured yet" is a real
        state at startup, and a summary that raised would have to be guarded at
        every call site that only wanted to print it.
        """
        if not samples:
            return cls(0, 0.0, 0.0, 0.0, 0.0)
        ordered = sorted(samples)
        return cls(
            count=len(ordered),
            fastest=ordered[0],
            median=percentile(ordered, 50),
            p95=percentile(ordered, 95),
            slowest=ordered[-1],
        )

    def __str__(self) -> str:
        if not self.count:
            return "no round trips measured yet"
        return (
            f"{self.count} round trips: fastest {self.fastest * 1000:.0f}ms, "
            f"median {self.median * 1000:.0f}ms, p95 {self.p95 * 1000:.0f}ms, "
            f"slowest {self.slowest * 1000:.0f}ms"
        )


def percentile(ordered: list[float], which: int) -> float:
    """Nearest-rank percentile of an already-sorted list.

    Nearest-rank returns an observation that actually occurred. Interpolating
    between two samples invents a duration nothing took, and a timeout defended
    with a number nobody measured is not a defence.
    """
    if not ordered:
        return 0.0
    rank = max(1, math.ceil(which / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


@dataclass(frozen=True, slots=True)
class Justification:
    """Whether the configured timeout is defensible against what we measured."""

    summary: Summary
    timeout_sec: float

    @property
    def headroom(self) -> float:
        """How many times the observed p95 fits into the timeout.

        Infinite when nothing has been measured or every call was instant —
        which is honest. An unmeasured timeout is not *thin*, it is unjustified,
        and :attr:`sufficient` is the property that says so.
        """
        return math.inf if self.summary.p95 <= 0 else self.timeout_sec / self.summary.p95

    @property
    def measured(self) -> bool:
        """Whether there is any evidence at all behind the number."""
        return self.summary.count > 0

    @property
    def sufficient(self) -> bool:
        """Measured, and with an order of magnitude to spare."""
        return self.measured and self.headroom >= COMFORTABLE_HEADROOM

    def __str__(self) -> str:
        if not self.measured:
            return (
                f"response_timeout_sec = {self.timeout_sec:g}s is UNJUSTIFIED: "
                "no round trips have been measured over the tunnel yet"
            )
        verdict = "ample" if self.sufficient else "THIN"
        margin = "inf" if math.isinf(self.headroom) else f"{self.headroom:.0f}x"
        return (
            f"response_timeout_sec = {self.timeout_sec:g}s against {self.summary}; "
            f"margin over p95 is {margin} — {verdict}. The timeout covers a push "
            "and an enqueue only; the opponent's thinking is bounded separately "
            "by turn_timeout_seconds, because inbound calls are fire-and-forget."
        )


def justify(log: LatencyLog, timeout_sec: float = DEFAULT_RESPONSE_TIMEOUT_SEC) -> Justification:
    """State, in writing, whether the timeout survives what we observed."""
    return Justification(log.summary(), timeout_sec)


class TimedTransport:
    """Wraps a transport and times every call.

    A decorator rather than timing inside :class:`~.mcp_client.OpponentClient`,
    so that what is measured is unambiguously the network round trip and not
    the retry loop wrapped around it. Timing the outer loop would fold four
    failed attempts and two backoff sleeps into a single "round trip" and make
    the tunnel look far worse than it is.
    """

    def __init__(
        self,
        inner: Transport,
        log: LatencyLog | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.inner = inner
        self.log = log if log is not None else LatencyLog()
        self._clock = clock

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        """Time one call. A failed call is not recorded as a round trip.

        A connection refused returns in microseconds and would drag the median
        toward zero, making a dying tunnel look like a fast one — the opposite
        of what the measurement is for.
        """
        started = self._clock()
        result: dict[str, Any] = self.inner.call(url, tool, payload, timeout)
        self.log.record(tool, self._clock() - started)
        return result
