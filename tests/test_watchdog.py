"""Tests for the stall watchdog."""

import pytest

from thief_agent.runtime.watchdog import (
    DEFAULT_WATCHDOG_TIMEOUT_SEC,
    Watchdog,
    WatchdogVerdict,
)


class FakeClock:
    def __init__(self, now: float = 500.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def watchdog(clock: FakeClock, timeout_sec: float = 60.0) -> tuple[Watchdog, list[str]]:
    events: list[str] = []
    dog = Watchdog(
        timeout_sec=timeout_sec,
        clock=clock,
        persist_state=lambda: events.append("persist"),
        shutdown=lambda: events.append("shutdown"),
    )
    return dog, events


class TestDefaults:
    def test_timeout_matches_appendix_f(self) -> None:
        assert DEFAULT_WATCHDOG_TIMEOUT_SEC == 60.0

    def test_non_positive_timeout_is_refused(self) -> None:
        with pytest.raises(ValueError, match="timeout_sec"):
            Watchdog(timeout_sec=0)


class TestLiveness:
    def test_a_fresh_watchdog_is_alive(self) -> None:
        dog, _ = watchdog(FakeClock())
        assert dog.check() is WatchdogVerdict.ALIVE

    def test_beating_keeps_it_alive_indefinitely(self) -> None:
        clock = FakeClock()
        dog, events = watchdog(clock)
        for _ in range(100):
            clock.advance(59.0)
            dog.beat()
            assert dog.check() is WatchdogVerdict.ALIVE
        assert events == []

    def test_silence_grows_without_beats(self) -> None:
        clock = FakeClock()
        dog, _ = watchdog(clock)
        clock.advance(10.0)
        assert dog.silence() == 10.0

    def test_a_beat_resets_silence(self) -> None:
        clock = FakeClock()
        dog, _ = watchdog(clock)
        clock.advance(50.0)
        dog.beat()
        assert dog.silence() == 0.0


class TestStall:
    def test_fires_at_the_threshold(self) -> None:
        clock = FakeClock()
        dog, events = watchdog(clock)
        clock.advance(60.0)
        assert dog.check() is WatchdogVerdict.SHUTDOWN
        assert events == ["persist", "shutdown"]

    def test_does_not_fire_just_before(self) -> None:
        clock = FakeClock()
        dog, events = watchdog(clock)
        clock.advance(59.999)
        assert dog.check() is WatchdogVerdict.ALIVE
        assert events == []

    def test_state_is_persisted_before_shutdown(self) -> None:
        """A recoverable sub-game is worth more than a crashed one."""
        clock = FakeClock()
        dog, events = watchdog(clock)
        clock.advance(100.0)
        dog.check()
        assert events.index("persist") < events.index("shutdown")

    def test_fires_only_once(self) -> None:
        """A second firing would overwrite the state captured at the stall."""
        clock = FakeClock()
        dog, events = watchdog(clock)
        clock.advance(100.0)
        for _ in range(5):
            assert dog.check() is WatchdogVerdict.SHUTDOWN
        assert events == ["persist", "shutdown"]


class TestDistinctFromDeadlines:
    def test_a_slow_but_beating_loop_is_not_a_stall(self) -> None:
        """Deadlines guard a request; the watchdog guards the process."""
        clock = FakeClock()
        dog, events = watchdog(clock)
        for _ in range(20):
            clock.advance(30.0)
            dog.beat()
        assert dog.check() is WatchdogVerdict.ALIVE
        assert events == []

    def test_a_silent_loop_stalls_even_with_no_pending_request(self) -> None:
        clock = FakeClock()
        dog, _ = watchdog(clock)
        clock.advance(61.0)
        assert dog.check() is WatchdogVerdict.SHUTDOWN

    def test_beats_are_counted(self) -> None:
        dog, _ = watchdog(FakeClock())
        dog.beat()
        dog.beat()
        assert dog.beats == 2
