"""What the round trips were, before anything is argued from them.

The raw record and its order statistics, kept apart from the timeout argument
in :mod:`.latency` that consumes them. Nothing here knows what a timeout is:
it collects durations and reports what they looked like, so the defence of the
configured budget is written in one place against numbers gathered in another.
"""

import math
from dataclasses import dataclass, field

__all__ = ["LatencyLog", "Summary", "percentile"]


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
