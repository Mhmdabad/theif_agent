"""The only module in this package allowed to know what time it is.

``guards/purity.py`` enforces that, and two things depend on it:

* a seeded self-play run is **reproducible**, because no wall-clock value reaches a sealed
  payload or a policy decision;
* tests can advance time by hand instead of sleeping, so the whole six-sub-game series runs in
  the zero-dependency test tier in well under a second.

The budget rules below are the ones a real kill-drill lost a game to: two timeouts that had never
been related to each other anywhere, and at runtime the wrong one won and the peer self-terminated
while perfectly healthy. They are checked at construction, so a configuration that would kill you
refuses to load rather than losing a counted game.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass, field
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...

    def stamp(self) -> str: ...


class MonotonicClock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def stamp(self) -> str:
        """An ISO-8601 UTC stamp for the wire (`TurnMessage.timestamp`).

        Lives here because purity rule P-3 makes this the only module allowed to know the
        time — the first attempt to stamp messages where they are built was (correctly)
        refused by the preflight. The stamp rides the message and never enters a sealed
        payload, so it cannot move a commit. Found by the 2026-08-04 dogfood run: nothing
        ever set the field, every outbound turn carried "", and a receiver pinned to the
        reference's ISO stamp refused the frame.
        """
        return datetime.datetime.now(datetime.timezone.utc).isoformat()


def poll_until(predicate, budget: float, interval: float, clock: Clock):
    """Call ``predicate`` until it returns something not-None, or our own budget runs out.

    Lives here because this is the module that owns the clock — ``guards/purity.py`` rule P-3
    keeps ``time`` out of every other module, and the networked driver needs to wait on a live
    socket without becoming the second place that knows what time it is.

    The budget is *ours*. A silent opponent is classified by rule (App. E) when this returns
    empty-handed; it is never a reason to self-terminate, which is why the transport's own
    give-up must outlast this (see ``Budgets``).
    """
    deadline = clock.now() + budget
    while clock.now() < deadline:
        got = predicate()
        if got is not None:
            return got
        clock.sleep(interval)
    return None


class FakeClock:
    """A clock that only moves when a test says so."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def sleep(self, seconds: float) -> None:
        """Advance rather than block, so a test can exercise a polling loop instantly."""
        self._t += seconds

    def advance(self, seconds: float) -> float:
        self._t += seconds
        return self._t

    def stamp(self) -> str:
        """Deterministic, and obviously synthetic: the fake epoch plus the fake seconds.

        Self-play, the golden, and the generated EVIDENCE all run on this clock, so their
        frames stay byte-reproducible under a seed while live play (MonotonicClock) stamps
        real wall-clock time.
        """
        return datetime.datetime.fromtimestamp(
            self._t, tz=datetime.timezone.utc).isoformat()


class BudgetError(Exception):
    pass


@dataclass(frozen=True)
class Budgets:
    """Timing budgets, reconciled at construction.

    The five rules, in the order they bite. Every violation is reported at once, because a
    configuration is fixed in one pass or not at all.
    """

    # 180s is DELIBERATE PRACTICE-PEER LENIENCY, not the book's number: the book fixes a 30s
    # response timeout for real play. A sparring partner that classified TIMEOUT at 30s would
    # punish a team mid-debugging for reading a stack trace; waiting longer costs only this
    # peer's own wall clock (LEAGUE-OPS §5 — budgets are yours). Calibrating for a counted
    # game? Run with --turn-timeout 30. (Named as deliberate after anrbj666's audit, B6.)
    turn_timeout: float = 180.0
    watchdog_timeout: float = 60.0
    poll_interval: float = 0.5
    connect_timeout: float = 30.0
    inbound_buffer_limit: int = 4

    def __post_init__(self) -> None:
        problems: list[str] = []
        if self.watchdog_timeout <= 0:
            problems.append("watchdog_timeout must be > 0 — an armed watchdog with no budget is "
                            "not armed")
        if self.poll_interval >= self.watchdog_timeout:
            problems.append(
                f"poll_interval ({self.poll_interval}) must be < watchdog_timeout "
                f"({self.watchdog_timeout}) — an idle loop beats once per poll, so a poll that "
                f"can outlast the watchdog self-terminates a healthy waiting peer")
        if self.connect_timeout > self.turn_timeout:
            problems.append(
                f"connect_timeout ({self.connect_timeout}) must be <= turn_timeout "
                f"({self.turn_timeout}) — an outbound give-up must never outlast our own rule "
                f"budget, or the transport abandons a peer the deadline still considers in-budget")
        if self.io_stall_timeout <= self.turn_timeout:
            problems.append(
                "io_stall_timeout must exceed turn_timeout — whatever a stalled transport does, "
                "OUR OWN turn deadline must expire first, so a silent opponent is classified by "
                "rule (App. E) and never by suicide")
        if self.inbound_buffer_limit < 1:
            problems.append(
                "inbound_buffer_limit must be >= 1 — a receiver with no reorder window turns an "
                "at-least-once retry race into a protocol violation (SPEC section 7.1); zero "
                "tolerance is not a tightening, it is a self-inflicted technical loss")
        if problems:
            raise BudgetError("timing budgets are not reconciled:\n  " + "\n  ".join(problems))

    @property
    def io_stall_timeout(self) -> float:
        return self.turn_timeout + self.watchdog_timeout


@dataclass
class DeadlineTracker:
    """One clock per *expected* message.

    There is deliberately no ``renew()``. A redelivered or early push proves the opponent is alive
    but does not discharge what it owes us, so it must not buy the sender more time — and the
    deadline is evaluated on every lap, including laps where a message *did* arrive, because a
    receiver that checks its clock only on an empty poll never checks it under a flood.
    """

    clock: Clock
    _deadline: float | None = field(default=None, init=False)
    _waiting_for: str | None = field(default=None, init=False)

    def expect(self, what: str, seconds: float) -> None:
        self._waiting_for = what
        self._deadline = self.clock.now() + seconds

    def clear(self) -> None:
        self._waiting_for = None
        self._deadline = None

    @property
    def waiting_for(self) -> str | None:
        return self._waiting_for

    def expired(self) -> bool:
        if self._deadline is None:
            return False
        return self.clock.now() >= self._deadline

    def remaining(self) -> float:
        if self._deadline is None:
            return float("inf")
        return max(0.0, self._deadline - self.clock.now())
