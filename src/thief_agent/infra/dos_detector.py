"""Gate three: recognising a bug, and locking the door on it.

Gates one and two are arithmetic. The quota counts, the bucket meters, and both
would let a broken agent send steadily forever — the bucket in particular is
*designed* to allow a sustained 30 a minute, which is exactly what an infinite
loop produces. Neither can tell a busy day from a defect.

FR-7.20 asks for the gate that can: recognise an anomalous send *pattern*, then
**lock API access entirely**, sacrificing one report to save the account. It is
backpressure plus a circuit breaker, and the phrase worth keeping is *sacrificing
one report*. Losing a match's points is a bad afternoon; losing the account is
the project.

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

**The lock does not expire.** A circuit breaker that half-opens after a timeout
is right for a flaky dependency and wrong here, because the fault is *ours*: the
loop is still running, and reopening the door hands it the account again. Only
:meth:`Detector.reset`, called deliberately once somebody has looked, clears it.
That is the "sacrifice" in the requirement — it is supposed to hurt slightly, or
it would not be a last resort.

**The lock is on disk**, for the reason the quota ledger is: a detector that
forgets on restart is defeated by a crash loop, which is one of the shapes the
bug it hunts actually takes.
"""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

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

LOCK_PATH_ENV = "GMAIL_LOCK_PATH"


class DosDetected(RuntimeError):
    """Raised when the pipeline is locked. Not retryable, by design."""


def lock_path(package: str, environ: "dict[str, str] | None" = None) -> Path:
    chosen = (environ if environ is not None else dict(os.environ)).get(LOCK_PATH_ENV)
    return Path(chosen) if chosen else Path(f".locked_{package.split('_')[0]}.json")


@dataclass
class Detector:
    """Watches the shape of recent sends and locks the pipeline on a bug."""

    path: Path
    now: Callable[[], float]
    burst_limit: int = BURST_LIMIT
    window_sec: float = WINDOW_SEC
    metronome_run: int = METRONOME_RUN
    tolerance: float = METRONOME_TOLERANCE
    history: int = 32
    recent: list[float] = field(default_factory=list, init=False)

    def _within_window(self, moment: float) -> list[float]:
        return [at for at in self.recent if moment - at <= self.window_sec]

    @property
    def locked(self) -> bool:
        return self.path.exists()

    def reason(self) -> str:
        """Why the lock was set, for whoever finds it. Empty when unlocked."""
        try:
            body = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return "locked, but the reason could not be read"
        return str(body.get("reason", "")) if isinstance(body, dict) else ""

    def check(self) -> None:
        """Refuse if the pipeline is locked. Called before anything else.

        Raises:
            DosDetected: always, while locked. There is no timeout and no
                half-open state: the fault is a bug in this process, and
                reopening the door while it still runs hands it the account.
        """
        if self.locked:
            raise DosDetected(
                f"the send pipeline is locked: {self.reason()}. Nothing goes out until "
                f"somebody looks at why and clears {self.path} deliberately. One report "
                "is worth less than the account"
            )

    def record(self) -> None:
        """Note that a send is happening, and lock if the pattern looks mechanical.

        Called on every send attempt, before the request. A detector fed only
        successes cannot see a loop that fails every time, which is the loop
        most likely to be running.

        Raises:
            DosDetected: if this send completes an anomalous pattern. The lock
                is written first, so a caller that ignores the exception still
                finds the door shut on the next attempt.
        """
        self.check()
        moment = self.now()
        self.recent.append(moment)
        self.recent = self.recent[-self.history :]

        inside = self._within_window(moment)
        if len(inside) > self.burst_limit:
            self._lock(
                f"{len(inside)} sends within {self.window_sec:g}s, over the burst "
                f"limit of {self.burst_limit}"
            )
        spread = self._metronome()
        if spread is not None:
            self._lock(
                f"{self.metronome_run + 1} sends spaced {spread:g}s apart to within "
                f"{self.tolerance:.0%} — that is a loop's cadence, not a match's"
            )

    def _metronome(self) -> float | None:
        """The mean interval, if the last run of them is suspiciously even.

        Returns ``None`` when there is not enough history or the spacing is
        irregular — which is what real activity looks like. Intervals of zero
        are treated as mechanical too: nothing human sends twice in the same
        instant.
        """
        needed = self.metronome_run + 1
        if len(self.recent) < needed:
            return None
        tail = self.recent[-needed:]
        gaps = [later - earlier for earlier, later in pairwise(tail)]
        mean = sum(gaps) / len(gaps)
        if mean <= 0:
            return 0.0
        if max(abs(gap - mean) for gap in gaps) / mean > self.tolerance:
            return None
        return mean

    def _lock(self, reason: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "w") as stream:
            json.dump({"reason": reason, "at": self.now()}, stream, sort_keys=True)
            stream.write("\n")
        raise DosDetected(
            f"send pipeline locked — {reason}. This is the circuit breaker: one report "
            f"is sacrificed to save the account. Investigate, then delete {self.path}"
        )

    def reset(self) -> None:
        """Clear the lock. Deliberate, and never done by a failure path."""
        self.path.unlink(missing_ok=True)
        self.recent.clear()
