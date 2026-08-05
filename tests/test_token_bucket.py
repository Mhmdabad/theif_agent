"""The rulebook's formula, its minimums, and the queue that makes it a limiter."""

from pathlib import Path
from typing import Any

import pytest

from thief_agent.infra.token_bucket import (
    CONCURRENT_REQUESTS,
    MAX_RETRIES,
    QUEUE_DEPTH,
    REQUESTS_PER_MINUTE,
    RETRY_BACKOFF_SEC,
    Limiter,
    QueueFull,
    RateLimitError,
    TokenBucket,
)
from thief_agent.shared.appendix_f import book_value


class Clock:
    """A monotonic clock a test can drive, in seconds."""

    def __init__(self, at: float = 1000.0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += seconds


def bucket(
    clock: Clock | None = None, capacity: float = 2.0, per_minute: float = 30.0
) -> TokenBucket:
    return TokenBucket(capacity=capacity, per_minute=per_minute, now=clock or Clock())


class TestTheFormula:
    def test_it_starts_full_because_silence_earns_burst(self) -> None:
        """A process that just started has by definition been quiet."""
        assert bucket().tokens() == 2.0

    def test_allow_spends_a_token(self) -> None:
        gate = bucket()
        assert gate.allow()
        assert gate.tokens() == 1.0

    def test_it_blocks_when_empty(self) -> None:
        gate = bucket()
        assert gate.allow()
        assert gate.allow()
        assert not gate.allow()

    def test_it_refills_at_r_times_delta_t(self) -> None:
        clock = Clock()
        gate = bucket(clock)
        gate.allow()
        gate.allow()
        clock.advance(2.0)  # r = 30/60 = 0.5 tokens/sec
        assert gate.tokens() == pytest.approx(1.0)

    def test_refill_is_capped_at_c(self) -> None:
        """min(C, ...) — silence earns burst, but only up to the capacity."""
        clock = Clock()
        gate = bucket(clock)
        gate.allow()
        gate.allow()
        clock.advance(10_000.0)
        assert gate.tokens() == 2.0

    def test_silence_really_is_rewarded(self) -> None:
        """The book's own phrasing, as a behaviour."""
        clock = Clock()
        gate = bucket(clock)
        gate.allow()
        gate.allow()
        assert not gate.allow()
        clock.advance(60.0)
        assert gate.allow() and gate.allow(), "a quiet minute should buy back the burst"

    def test_the_rate_is_per_minute_divided_by_sixty(self) -> None:
        assert bucket(per_minute=30.0).rate == pytest.approx(0.5)


class TestRefillIsComputedNotTicked:
    def test_a_process_that_was_stopped_for_an_hour_comes_back_full(self) -> None:
        """No thread, no timer — Δt is whatever the clock says it is."""
        clock = Clock()
        gate = bucket(clock)
        gate.allow()
        gate.allow()
        clock.advance(3600.0)
        assert gate.tokens() == 2.0

    def test_a_clock_that_steps_backwards_does_not_break_it(self) -> None:
        """NTP correction, or a laptop resuming from sleep."""
        clock = Clock()
        gate = bucket(clock)
        gate.allow()
        before = gate.tokens()
        clock.advance(-500.0)
        assert gate.tokens() == pytest.approx(before), "Δt is clamped at zero, not negative"

    def test_asking_repeatedly_does_not_add_tokens(self) -> None:
        gate = bucket(Clock())
        gate.allow()
        for _ in range(50):
            gate.tokens()
        assert gate.tokens() == 1.0


class TestWaitForReportsRatherThanSleeps:
    def test_it_is_zero_when_a_token_is_available(self) -> None:
        assert bucket().wait_for() == 0.0

    def test_it_is_the_time_to_earn_one_token(self) -> None:
        gate = bucket()
        gate.allow()
        gate.allow()
        assert gate.wait_for() == pytest.approx(2.0), "0.5 tokens/sec, so one token is 2s"

    def test_it_shrinks_as_time_passes(self) -> None:
        clock = Clock()
        gate = bucket(clock)
        gate.allow()
        gate.allow()
        clock.advance(1.0)
        assert gate.wait_for() == pytest.approx(1.0)

    def test_it_does_not_spend_a_token(self) -> None:
        gate = bucket()
        gate.wait_for()
        assert gate.tokens() == 2.0


class TestTheAppendixFMinimumsAreFloorsNotDefaults:
    def test_the_constants_come_from_the_table_not_from_here(self) -> None:
        """A constant that merely agrees with the table can silently disagree."""
        assert book_value("rate_limiter_gatekeeper", "requests_per_minute") == REQUESTS_PER_MINUTE
        assert book_value("rate_limiter_gatekeeper", "concurrent_requests") == CONCURRENT_REQUESTS
        assert book_value("rate_limiter_gatekeeper", "queue_depth") == QUEUE_DEPTH
        assert book_value("rate_limiter_gatekeeper", "max_retries") == MAX_RETRIES
        assert book_value("rate_limiter_gatekeeper", "retry_backoff_sec") == RETRY_BACKOFF_SEC

    def test_the_book_values_are_what_the_rulebook_prints(self) -> None:
        assert (REQUESTS_PER_MINUTE, CONCURRENT_REQUESTS) == (30, 2)
        assert (RETRY_BACKOFF_SEC, MAX_RETRIES, QUEUE_DEPTH) == (5, 3, 100)

    def test_a_rate_below_the_minimum_is_refused(self) -> None:
        with pytest.raises(RateLimitError, match="minimum in Appendix F"):
            TokenBucket(per_minute=29.0)

    def test_a_capacity_below_the_minimum_is_refused(self) -> None:
        with pytest.raises(RateLimitError, match="concurrent_requests is a minimum"):
            TokenBucket(capacity=1.0)

    def test_going_above_a_minimum_is_allowed(self) -> None:
        """*Minimum* means raise only — upward is legal and sometimes sensible."""
        assert TokenBucket(per_minute=120.0, capacity=10.0).tokens() == 10.0

    @pytest.mark.parametrize(
        "lowered",
        [{"queue_depth": 99}, {"max_retries": 2}, {"backoff_sec": 4.0}],
    )
    def test_the_limiter_refuses_each_minimum_being_lowered(self, lowered: dict[str, Any]) -> None:
        with pytest.raises(RateLimitError, match="minimum in Appendix F"):
            Limiter(**lowered)

    def test_the_defaults_are_the_book_values(self) -> None:
        limiter = Limiter()
        assert limiter.queue_depth == QUEUE_DEPTH
        assert limiter.max_retries == MAX_RETRIES
        assert limiter.backoff_sec == float(RETRY_BACKOFF_SEC)


class TestTheQueueIsWhereBackpressureLives:
    def test_a_request_with_a_token_available_waits_for_nothing(self) -> None:
        assert Limiter(bucket=bucket()).enter() == 0.0

    def test_a_request_with_no_token_is_told_how_long_to_wait(self) -> None:
        limiter = Limiter(bucket=bucket())
        limiter.enter()
        limiter.enter()
        assert limiter.enter() == pytest.approx(2.0)

    def test_only_waiting_requests_occupy_the_queue(self) -> None:
        limiter = Limiter(bucket=bucket())
        limiter.enter()
        assert limiter.waiting == 0, "a request that went straight through is not waiting"

    def test_a_full_queue_refuses_rather_than_growing(self) -> None:
        """An unbounded queue turns a rate problem into a memory problem."""
        limiter = Limiter(bucket=bucket(), queue_depth=QUEUE_DEPTH)
        limiter.enter()
        limiter.enter()
        for _ in range(QUEUE_DEPTH):
            limiter.enter()
        with pytest.raises(QueueFull, match="queue depth is 100"):
            limiter.enter()

    def test_queue_full_is_a_rate_limit_error(self) -> None:
        """So a caller may catch the general case without knowing the specifics."""
        assert issubclass(QueueFull, RateLimitError)

    def test_leaving_frees_a_slot(self) -> None:
        limiter = Limiter(bucket=bucket())
        limiter.enter()
        limiter.enter()
        limiter.enter()
        assert limiter.waiting == 1
        limiter.leave()
        assert limiter.waiting == 0

    def test_leaving_more_often_than_entering_does_not_go_negative(self) -> None:
        limiter = Limiter(bucket=bucket())
        limiter.leave()
        limiter.leave()
        assert limiter.waiting == 0


class TestBackoffGrowsAndThenStops:
    def test_the_first_backoff_is_the_configured_base(self) -> None:
        assert Limiter().backoff_for(1) == 5.0

    def test_it_doubles(self) -> None:
        limiter = Limiter()
        assert [limiter.backoff_for(n) for n in (1, 2, 3)] == [5.0, 10.0, 20.0]

    def test_asking_past_max_retries_raises_rather_than_returning_a_sentinel(self) -> None:
        """'Retry forever' is the behaviour that gets an account suspended."""
        with pytest.raises(RateLimitError, match="retries exhausted"):
            Limiter().backoff_for(MAX_RETRIES + 1)

    def test_attempts_are_numbered_from_one(self) -> None:
        with pytest.raises(RateLimitError, match="numbered from 1"):
            Limiter().backoff_for(0)


class TestTheseAreRateTokensAndNothingElse:
    def test_the_module_has_no_notion_of_llm_or_oauth_tokens(self) -> None:
        """Three unrelated things in this project are called 'token'."""
        from thief_agent.infra import token_bucket

        body = Path(str(token_bucket.__file__)).read_text()
        assert "refresh_token" not in body
        assert "token_budget" not in body
