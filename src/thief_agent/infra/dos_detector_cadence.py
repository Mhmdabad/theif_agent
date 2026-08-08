"""Gate three's eye: what an anomalous send *pattern* is, and where the lines are.

Separated from :mod:`.dos_detector`, which owns the history, the clock and the
lock. Nothing here touches disk or time: given a list of moments it answers only
*what shape is this*, which is the part the thresholds are tuned against.

**What "anomalous" means here.** Not volume — volume is what the other two gates
are for. The signal is *regularity*. A person, or an agent playing matches, sends
in clumps with irregular gaps: a report at the end of one game, another twenty
minutes later. A loop sends with the spacing of its own iteration, and that
spacing is suspiciously even. So the detector watches the **variation** in the
intervals between sends, and trips when a burst arrives too evenly to be a
sequence of real events.

Two independent triggers, because a bug can be fast or merely relentless:

* **burst** — more than ``burst_limit`` sends inside ``window_sec``;
* **metronome** — a run of sends whose intervals are nearly identical, which is
  what code does and people do not.

The two read the same history over **different spans**, and that is deliberate.
The burst rule asks "how many just now", so it counts inside ``window_sec``. The
cadence rule asks "what shape", and a slow loop — one send every few minutes,
forever — never puts enough samples inside a one-minute window to have a shape
at all. Windowing the history before measuring cadence would leave the metronome
trigger able to see only fast patterns, which the burst rule already catches, and
blind to the relentless-but-slow loop it exists for.
"""

from dataclasses import dataclass
from itertools import pairwise

BURST_LIMIT = 5
"""Sends inside :data:`WINDOW_SEC` that count as a burst.

Above anything a real match produces — one report per game — and far below the
30/minute the token bucket would happily allow.
"""

WINDOW_SEC = 60.0
"""The burst window."""

METRONOME_RUN = 4
"""Consecutive intervals that must be near-identical to look mechanical."""

METRONOME_TOLERANCE = 0.05
"""Relative spread below which a run of intervals is machine-regular.

Five percent. Human-paced events do not land this evenly; a loop with a fixed
sleep does almost nothing else.
"""


@dataclass(frozen=True)
class Thresholds:
    """The tuned lines, and the verdict they add up to.

    Built afresh from the detector's own fields on every send rather than kept
    alongside it, so a caller that reassigns one of those fields after
    construction is read live instead of snapshotted.
    """

    burst_limit: int = BURST_LIMIT
    window_sec: float = WINDOW_SEC
    metronome_run: int = METRONOME_RUN
    tolerance: float = METRONOME_TOLERANCE

    def _within_window(self, recent: list[float], moment: float) -> list[float]:
        return [at for at in recent if moment - at <= self.window_sec]

    def anomaly(self, recent: list[float], moment: float) -> str | None:
        """Why this send looks mechanical, or ``None`` when it does not.

        Burst first, cadence second, in the order the two triggers have always
        run: the burst reason is the one reported when both would fire.
        """
        inside = self._within_window(recent, moment)
        if len(inside) > self.burst_limit:
            return (
                f"{len(inside)} sends within {self.window_sec:g}s, over the burst "
                f"limit of {self.burst_limit}"
            )
        spread = self._metronome(recent)
        if spread is not None:
            return (
                f"{self.metronome_run + 1} sends spaced {spread:g}s apart to within "
                f"{self.tolerance:.0%} — that is a loop's cadence, not a match's"
            )
        return None

    def _metronome(self, recent: list[float]) -> float | None:
        """The mean interval, if the last run of them is suspiciously even.

        Returns ``None`` when there is not enough history or the spacing is
        irregular — which is what real activity looks like. Intervals of zero
        are treated as mechanical too: nothing human sends twice in the same
        instant.
        """
        needed = self.metronome_run + 1
        if len(recent) < needed:
            return None
        tail = recent[-needed:]
        gaps = [later - earlier for earlier, later in pairwise(tail)]
        mean = sum(gaps) / len(gaps)
        if mean <= 0:
            return 0.0
        if max(abs(gap - mean) for gap in gaps) / mean > self.tolerance:
            return None
        return mean
