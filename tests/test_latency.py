"""Measuring the tunnel, and defending the timeout with what was measured."""

from typing import Any

import pytest

from thief_agent.infra.latency import (
    COMFORTABLE_HEADROOM,
    DEFAULT_RESPONSE_TIMEOUT_SEC,
    Justification,
    LatencyLog,
    Summary,
    TimedTransport,
    justify,
    percentile,
)


class FakeClock:
    """Reads back scripted start/end pairs, one pair per timed call.

    Each pair starts from zero rather than accumulating, so a duration comes
    back exactly as written instead of as ``0.20000000000004547``. Nothing in
    the code under test requires the clock to advance monotonically across
    calls, and exact assertions are worth more here than realism.
    """

    def __init__(self, *durations: float) -> None:
        self._ticks: list[float] = []
        for duration in durations:
            self._ticks += [0.0, duration]

    def __call__(self) -> float:
        return self._ticks.pop(0)


class Echo:
    def __init__(self, *failures: Exception) -> None:
        self._failures = list(failures)
        self.calls = 0

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls += 1
        if self._failures:
            raise self._failures.pop(0)
        return {"ok": True}


class TestPercentile:
    def test_it_returns_an_observation_that_actually_happened(self) -> None:
        """Interpolating invents a duration nothing took.

        A timeout defended with a number nobody measured is not a defence.
        """
        ordered = [0.1, 0.2, 0.3, 0.4]
        assert percentile(ordered, 95) in ordered

    @pytest.mark.parametrize(
        ("which", "expected"),
        [(50, 0.3), (95, 0.5), (100, 0.5), (1, 0.1)],
    )
    def test_nearest_rank(self, which: int, expected: float) -> None:
        assert percentile([0.1, 0.2, 0.3, 0.4, 0.5], which) == expected

    def test_a_single_sample_is_every_percentile(self) -> None:
        assert percentile([0.7], 50) == percentile([0.7], 95) == 0.7

    def test_an_empty_list_is_zero_rather_than_an_error(self) -> None:
        assert percentile([], 95) == 0.0


class TestTheLog:
    def test_it_keeps_samples_per_tool_and_overall(self) -> None:
        log = LatencyLog()
        log.record("receive_turn", 0.05)
        log.record("negotiate", 0.09)
        log.record("receive_turn", 0.07)
        assert log.samples == [0.05, 0.09, 0.07]
        assert log.by_tool == {"receive_turn": [0.05, 0.07], "negotiate": [0.09]}

    def test_a_negative_round_trip_is_a_broken_clock_not_data(self) -> None:
        with pytest.raises(ValueError, match="cannot be negative"):
            LatencyLog().record("receive_turn", -0.01)

    def test_zero_is_allowed_because_a_fast_loopback_call_really_is_zero(self) -> None:
        LatencyLog().record("negotiate", 0.0)


class TestSummary:
    def test_it_reports_the_shape_of_the_distribution(self) -> None:
        summary = Summary.of([0.30, 0.10, 0.50, 0.20, 0.40])
        assert (summary.count, summary.fastest, summary.slowest) == (5, 0.10, 0.50)
        assert (summary.median, summary.p95) == (0.30, 0.50)

    def test_nothing_measured_is_a_real_state_not_an_error(self) -> None:
        """A summary that raised would need guarding at every print site."""
        summary = Summary.of([])
        assert summary.count == 0
        assert "no round trips measured" in str(summary)

    def test_it_reads_in_milliseconds_because_that_is_the_scale(self) -> None:
        assert "median 200ms" in str(Summary.of([0.1, 0.2, 0.3]))

    def test_it_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            Summary.of([0.1]).count = 9  # type: ignore[misc]


class TestJustifyingTheTimeout:
    def test_a_healthy_tunnel_leaves_ample_margin(self) -> None:
        log = LatencyLog()
        for sample in [0.08, 0.09, 0.11, 0.10, 0.12]:
            log.record("receive_turn", sample)
        verdict = justify(log)
        assert verdict.sufficient
        assert verdict.headroom > 200
        assert "ample" in str(verdict)

    def test_a_degraded_tunnel_is_called_thin(self) -> None:
        """One stall an order of magnitude past normal costs a whole sub-game.

        A technical loss scores zero for both sides, so the margin that matters
        is not the average call but the worst one the match will see.
        """
        log = LatencyLog()
        for sample in [2.0, 25.0, 3.0]:
            log.record("receive_turn", sample)
        verdict = justify(log)
        assert not verdict.sufficient
        assert "THIN" in str(verdict)

    def test_the_boundary_is_the_stated_ratio(self) -> None:
        log = LatencyLog()
        log.record("receive_turn", DEFAULT_RESPONSE_TIMEOUT_SEC / COMFORTABLE_HEADROOM)
        assert justify(log).sufficient
        log.record("receive_turn", DEFAULT_RESPONSE_TIMEOUT_SEC / COMFORTABLE_HEADROOM + 0.01)
        assert not justify(log).sufficient

    def test_an_unmeasured_timeout_is_unjustified_rather_than_generous(self) -> None:
        """The distinction the rulebook asks for: evidence, not a plausible number."""
        verdict = justify(LatencyLog())
        assert not verdict.measured
        assert not verdict.sufficient
        assert "UNJUSTIFIED" in str(verdict)

    def test_instant_calls_report_infinite_headroom_honestly(self) -> None:
        log = LatencyLog()
        log.record("negotiate", 0.0)
        verdict = justify(log)
        assert verdict.measured
        assert "inf" in str(verdict)

    def test_it_names_what_the_timeout_is_actually_covering(self) -> None:
        """The whole argument of the module, restated where anyone will read it.

        Adding the opponent's think time to the network time would say 30s is
        broken, because ``step_deadline_seconds`` is 30 on its own. It is not
        broken: inbound calls are fire-and-forget, so this timeout covers a
        push and an enqueue.
        """
        log = LatencyLog()
        log.record("receive_turn", 0.1)
        assert "fire-and-forget" in str(justify(log))
        assert "turn_timeout_seconds" in str(justify(log))

    def test_a_raised_timeout_is_honoured(self) -> None:
        """Negotiable upward: a minimum may be raised, never lowered."""
        log = LatencyLog()
        log.record("receive_turn", 4.0)
        assert not justify(log, 30.0).sufficient
        assert justify(log, 60.0).headroom == 15.0

    def test_it_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            Justification(Summary.of([0.1]), 30.0).timeout_sec = 1.0  # type: ignore[misc]


class TestTimedTransport:
    def test_it_records_the_round_trip(self) -> None:
        transport = TimedTransport(Echo(), clock=FakeClock(0.25))
        transport.call("https://x/mcp", "receive_turn", {}, 30.0)
        assert transport.log.samples == [0.25]

    def test_it_passes_the_call_through_unchanged(self) -> None:
        inner = Echo()
        assert TimedTransport(inner, clock=FakeClock(0.1)).call("u", "t", {}, 1.0) == {"ok": True}
        assert inner.calls == 1

    def test_a_failed_call_is_not_a_round_trip(self) -> None:
        """A connection refused returns in microseconds.

        Recording it would drag the median toward zero and make a dying tunnel
        look like a fast one — the opposite of what the measurement is for.
        """
        transport = TimedTransport(Echo(ConnectionError("refused")), clock=FakeClock(0.0001))
        with pytest.raises(ConnectionError):
            transport.call("u", "receive_turn", {}, 30.0)
        assert transport.log.samples == []

    def test_it_measures_one_attempt_rather_than_the_retry_loop(self) -> None:
        """Timing outside the retries would fold backoff sleeps into a round trip.

        Four failed attempts and two five-second waits recorded as a single
        sample would make a healthy tunnel look unusable.
        """
        from thief_agent.infra.mcp_client import ClientSettings, OpponentClient

        transport = TimedTransport(
            Echo(TimeoutError(), TimeoutError()), clock=FakeClock(0.05, 0.05, 0.05)
        )
        settings = ClientSettings(opponent_url="https://x.ngrok-free.app", retry_backoff_sec=0.0)
        OpponentClient(transport, settings).call("receive_turn", {})
        assert transport.log.samples == [0.05]

    def test_it_shares_a_log_when_given_one(self) -> None:
        log = LatencyLog()
        TimedTransport(Echo(), log, clock=FakeClock(0.2)).call("u", "negotiate", {}, 1.0)
        assert log.by_tool == {"negotiate": [0.2]}
