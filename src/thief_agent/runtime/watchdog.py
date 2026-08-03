"""Watching the main loop for a stall.

Appendix E rule 7. The deadline tracker guards a single request; the watchdog
guards the **process**. They answer different questions: *did this call take too
long* versus *is anything still happening at all*.

The distinction matters because the failures that kill a match are usually not
one slow request. A language model that hangs, a transport that neither returns
nor errors, a loop waiting on a condition that will never hold — none of those
trip a per-request timeout, and all of them end the match with no result.

On detecting a stall the watchdog **persists state and shuts down cleanly**
rather than letting the process die. The rulebook is explicit that a controlled
shutdown preserving state is preferable to losing the match entirely: a
recoverable sub-game is worth more than a crashed one.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

DEFAULT_WATCHDOG_TIMEOUT_SEC = 60.0
"""Appendix F. Negotiable, so a parameter rather than a constant."""


class WatchdogVerdict(Enum):
    ALIVE = "alive"
    SHUTDOWN = "shutdown"


@dataclass
class Watchdog:
    """Monitors heartbeats and triggers a controlled shutdown on a stall.

    Both the clock and the shutdown actions are injected. A watchdog tested
    with real sleeps and a real shutdown is a watchdog that is barely tested,
    and this is the component that decides whether a bad match ends
    recoverably or not at all.
    """

    timeout_sec: float = DEFAULT_WATCHDOG_TIMEOUT_SEC
    clock: Callable[[], float] = time.monotonic
    persist_state: Callable[[], None] = lambda: None
    shutdown: Callable[[], None] = lambda: None
    last_beat: float = field(default=0.0)
    beats: int = 0
    fired: bool = False

    def __post_init__(self) -> None:
        if self.timeout_sec <= 0:
            raise ValueError(f"timeout_sec must be > 0, got {self.timeout_sec}")
        self.last_beat = self.clock()

    def beat(self) -> None:
        """Record that the main loop is still making progress."""
        self.last_beat = self.clock()
        self.beats += 1

    def silence(self) -> float:
        """Seconds since the last heartbeat."""
        return self.clock() - self.last_beat

    def check(self) -> WatchdogVerdict:
        """Assess liveness, shutting down on a stall.

        Persists state *before* shutting down, and only once: a second firing
        would overwrite the state captured at the moment of the stall with
        whatever the process looks like afterwards, which is worth less.
        """
        if self.fired:
            return WatchdogVerdict.SHUTDOWN
        if self.silence() < self.timeout_sec:
            return WatchdogVerdict.ALIVE
        self.fired = True
        self.persist_state()
        self.shutdown()
        return WatchdogVerdict.SHUTDOWN
