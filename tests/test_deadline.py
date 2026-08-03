"""Tests for request deadlines."""

import pytest

from thief_agent.runtime.deadline import (
    DEFAULT_RESPONSE_TIMEOUT_SEC,
    Deadline,
    DeadlineExpiredError,
    DeadlineTracker,
)


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestDefaults:
    def test_timeout_matches_appendix_f(self) -> None:
        assert DEFAULT_RESPONSE_TIMEOUT_SEC == 30.0

    def test_non_positive_timeout_is_refused(self) -> None:
        with pytest.raises(ValueError, match="timeout_sec"):
            DeadlineTracker(timeout_sec=0)


class TestExpiry:
    def test_a_fresh_deadline_has_the_full_budget(self) -> None:
        clock = FakeClock()
        tracker = DeadlineTracker(timeout_sec=30.0, clock=clock)
        assert tracker.remaining(tracker.start()) == 30.0

    def test_remaining_shrinks_with_time(self) -> None:
        clock = FakeClock()
        tracker = DeadlineTracker(timeout_sec=30.0, clock=clock)
        deadline = tracker.start()
        clock.advance(10.0)
        assert tracker.remaining(deadline) == 20.0

    def test_remaining_never_goes_negative(self) -> None:
        clock = FakeClock()
        tracker = DeadlineTracker(timeout_sec=1.0, clock=clock)
        deadline = tracker.start()
        clock.advance(100.0)
        assert tracker.remaining(deadline) == 0.0

    def test_not_expired_before_the_budget(self) -> None:
        clock = FakeClock()
        tracker = DeadlineTracker(timeout_sec=30.0, clock=clock)
        deadline = tracker.start()
        clock.advance(29.999)
        tracker.check(deadline)

    def test_expired_exactly_at_the_budget(self) -> None:
        """The boundary is a failure, not a grace period."""
        clock = FakeClock()
        tracker = DeadlineTracker(timeout_sec=30.0, clock=clock)
        deadline = tracker.start()
        clock.advance(30.0)
        with pytest.raises(DeadlineExpiredError):
            tracker.check(deadline)


class TestFailureNotPatience:
    def test_expiry_raises_rather_than_returning_a_flag(self) -> None:
        """A missed deadline is a failure, not an invitation to wait longer."""
        with pytest.raises(DeadlineExpiredError):
            Deadline(expires_at=0.0, label="commit").check(now=1.0)

    def test_the_error_names_the_request(self) -> None:
        with pytest.raises(DeadlineExpiredError, match="commit exceeded"):
            Deadline(expires_at=0.0, label="commit").check(now=1.0)

    def test_an_unlabelled_deadline_still_reports(self) -> None:
        with pytest.raises(DeadlineExpiredError, match="request exceeded"):
            Deadline(expires_at=0.0).check(now=1.0)

    def test_it_is_a_timeout_error(self) -> None:
        """So the client's retry logic treats it as the transport fault it is."""
        assert issubclass(DeadlineExpiredError, TimeoutError)


class TestBookkeeping:
    def test_issued_deadlines_are_recorded(self) -> None:
        tracker = DeadlineTracker(clock=FakeClock())
        tracker.start("a")
        tracker.start("b")
        assert [d.label for d in tracker.issued] == ["a", "b"]

    def test_expired_count_reflects_the_clock(self) -> None:
        clock = FakeClock()
        tracker = DeadlineTracker(timeout_sec=10.0, clock=clock)
        tracker.start("early")
        clock.advance(5.0)
        tracker.start("late")
        clock.advance(6.0)
        assert tracker.expired_count() == 1

    def test_a_deadline_is_frozen(self) -> None:
        import dataclasses

        with pytest.raises(dataclasses.FrozenInstanceError):
            Deadline(expires_at=1.0).expires_at = 2.0  # type: ignore[misc]
