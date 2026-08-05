"""Three gates in order, and a 429 that is honoured rather than argued with."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from thief_agent.infra.dos_detector import Detector
from thief_agent.infra.gatekeeper import (
    TOO_MANY_REQUESTS,
    Gatekeeper,
    Rejected,
    TooManyRequests,
    Wait,
    status_code_of,
)
from thief_agent.infra.quota import Quota
from thief_agent.infra.token_bucket import Limiter, RateLimitError, TokenBucket


class Clock:
    def __init__(self, at: float = 1000.0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += seconds


def gatekeeper(tmp_path: Path, limit: int = 10, capacity: float = 2.0) -> Gatekeeper:
    clock = Clock()
    return Gatekeeper(
        detector=Detector(path=tmp_path / ".locked_thief.json", now=clock),
        quota=Quota(
            path=tmp_path / ".quota_thief.json", limit=limit, now=lambda: datetime.now(UTC)
        ),
        limiter=Limiter(bucket=TokenBucket(capacity=capacity, per_minute=30.0, now=clock)),
    )


class TestAllThreeGatesRun:
    def test_a_clean_request_is_admitted(self, tmp_path: Path) -> None:
        assert gatekeeper(tmp_path).admit() is None

    def test_admission_spends_a_quota_slot(self, tmp_path: Path) -> None:
        """Reserved before the send, so a crash mid-flight cannot go uncounted."""
        gate = gatekeeper(tmp_path)
        gate.admit()
        assert gate.quota.used() == 1

    def test_admission_spends_a_token(self, tmp_path: Path) -> None:
        gate = gatekeeper(tmp_path)
        gate.admit()
        assert gate.limiter.bucket.tokens() == 1.0


class TestTheOrderIsCheapestAndMostFinalFirst:
    def test_a_locked_pipeline_is_refused_before_the_quota_is_touched(self, tmp_path: Path) -> None:
        """Nothing should be spent finding out the door is shut."""
        (tmp_path / ".locked_thief.json").write_text(json.dumps({"reason": "earlier"}))
        gate = gatekeeper(tmp_path)
        with pytest.raises(Rejected, match="DOS detector"):
            gate.admit()
        assert gate.quota.used() == 0
        assert gate.limiter.bucket.tokens() == 2.0

    def test_an_exhausted_quota_is_refused_before_a_token_is_spent(self, tmp_path: Path) -> None:
        """A request that will be refused outright should not wait for a token."""
        gate = gatekeeper(tmp_path, limit=1)
        gate.admit()
        tokens = gate.limiter.bucket.tokens()
        with pytest.raises(Rejected, match="quota"):
            gate.admit()
        assert gate.limiter.bucket.tokens() == tokens

    def test_each_refusal_names_its_gate(self, tmp_path: Path) -> None:
        """'Blocked' with no reason sends somebody to read three modules."""
        (tmp_path / ".locked_thief.json").write_text(json.dumps({"reason": "x"}))
        with pytest.raises(Rejected, match="^DOS detector:"):
            gatekeeper(tmp_path).admit()


class TestTheBucketSaysNotYetRatherThanNo:
    def test_an_empty_bucket_returns_a_wait(self, tmp_path: Path) -> None:
        gate = gatekeeper(tmp_path)
        gate.admit()
        gate.admit()
        waited = gate.admit()
        assert isinstance(waited, Wait)
        assert waited.seconds == pytest.approx(2.0)

    def test_a_wait_is_not_a_refusal(self, tmp_path: Path) -> None:
        gate = gatekeeper(tmp_path)
        gate.admit()
        gate.admit()
        assert gate.admit() is not None, "a Wait, not an exception"

    def test_a_wait_reads_as_a_sentence(self, tmp_path: Path) -> None:
        assert str(Wait(2.0, "rate limiter: no token available yet")).startswith("wait 2s")

    def test_a_full_queue_is_a_refusal(self, tmp_path: Path) -> None:
        """Backpressure has a limit, and past it the answer is no."""
        gate = gatekeeper(tmp_path, limit=1000)
        for _ in range(110):
            try:
                gate.admit()
            except Rejected as exc:
                assert "rate limiter" in str(exc)
                return
        pytest.fail("the queue never filled")

    def test_release_frees_a_queue_slot(self, tmp_path: Path) -> None:
        gate = gatekeeper(tmp_path)
        gate.admit()
        gate.admit()
        gate.admit()
        assert gate.limiter.waiting == 1
        gate.release()
        assert gate.limiter.waiting == 0


class TestAttemptsAreRecordedSeparately:
    def test_recording_is_not_part_of_admission(self, tmp_path: Path) -> None:
        """A caller admitted but not yet sending has attempted nothing."""
        gate = gatekeeper(tmp_path)
        gate.admit()
        assert gate.detector.recent == []

    def test_recording_feeds_the_detector(self, tmp_path: Path) -> None:
        gate = gatekeeper(tmp_path)
        gate.admit()
        gate.record_attempt()
        assert len(gate.detector.recent) == 1


class TestA429IsHonouredNotRetried:
    def test_it_produces_a_wait_of_at_least_the_configured_backoff(self, tmp_path: Path) -> None:
        gate = gatekeeper(tmp_path)
        assert gate.on_429(attempt=1).retry_after == 5.0

    def test_a_larger_retry_after_from_the_provider_wins(self, tmp_path: Path) -> None:
        """It knows about its own window; we are guessing."""
        assert gatekeeper(tmp_path).on_429(attempt=1, retry_after=90.0).retry_after == 90.0

    def test_a_smaller_retry_after_does_not_shorten_our_backoff(self, tmp_path: Path) -> None:
        """A provider suggesting 1s after two refusals is optimistic on our behalf."""
        gate = gatekeeper(tmp_path)
        assert gate.on_429(attempt=2, retry_after=1.0).retry_after == 10.0

    def test_there_is_no_zero_wait_path(self, tmp_path: Path) -> None:
        """FR-7.22: re-sending immediately is what gets an account suspended."""
        gate = gatekeeper(tmp_path)
        for attempt in (1, 2, 3):
            assert gate.on_429(attempt=attempt, retry_after=0.0).retry_after > 0

    def test_it_also_spends_a_token(self, tmp_path: Path) -> None:
        """The one authoritative signal that our own rate limiting was wrong."""
        gate = gatekeeper(tmp_path)
        before = gate.limiter.bucket.tokens()
        gate.on_429(attempt=1)
        assert gate.limiter.bucket.tokens() == before - 1.0

    def test_retries_run_out(self, tmp_path: Path) -> None:
        gate = gatekeeper(tmp_path)
        with pytest.raises(RateLimitError, match="retries exhausted"):
            gate.on_429(attempt=4)

    def test_the_backoff_grows_between_attempts(self, tmp_path: Path) -> None:
        gate = gatekeeper(tmp_path)
        assert [gate.on_429(attempt=n).retry_after for n in (1, 2, 3)] == [5.0, 10.0, 20.0]

    def test_it_returns_rather_than_raises_so_the_caller_decides(self, tmp_path: Path) -> None:
        assert isinstance(gatekeeper(tmp_path).on_429(attempt=1), TooManyRequests)

    def test_the_message_says_why_insisting_is_dangerous(self, tmp_path: Path) -> None:
        assert "suspended" in str(gatekeeper(tmp_path).on_429(attempt=1))


class TestReadingTheStatusCode:
    def test_the_constant_is_429(self) -> None:
        assert TOO_MANY_REQUESTS == 429

    def test_a_bare_integer(self) -> None:
        assert status_code_of(429) == 429

    def test_a_status_code_attribute(self) -> None:
        class Error:
            status_code = 429

        assert status_code_of(Error()) == 429

    def test_a_google_http_error_shape(self) -> None:
        """``HttpError`` carries ``resp.status`` and nothing more convenient."""

        class Response:
            status = 429

        class HttpError:
            resp = Response()

        assert status_code_of(HttpError()) == 429

    def test_a_code_attribute(self) -> None:
        class Error:
            code = 503

        assert status_code_of(Error()) == 503

    def test_something_with_no_status_at_all(self) -> None:
        assert status_code_of(ValueError("network went away")) is None

    def test_a_non_integer_status_is_not_taken(self) -> None:
        class Error:
            status_code = "429"

        assert status_code_of(Error()) is None

    def test_a_caller_may_supply_its_own_reader(self) -> None:
        """So a library with a fourth shape does not need a change here."""
        assert status_code_of("whatever", reader=lambda _: 429) == 429

    def test_reading_several_shapes_is_the_point(self) -> None:
        """A rule that fired for one exception type would stop firing on upgrade."""

        class ByAttribute:
            status_code = 429

        class ByResponse:
            class resp:  # noqa: N801
                status = 429

        assert {
            status_code_of(429),
            status_code_of(ByAttribute()),
            status_code_of(ByResponse()),
        } == {429}
