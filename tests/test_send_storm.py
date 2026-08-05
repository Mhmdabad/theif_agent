"""The scenario the Gatekeeper exists for, run end to end against a counting API.

FR-7.18 states the threat as a question: *what happens when an infinite loop
starts firing thousands of messages a minute?* Every gate has been tested
against its own rules. None of them has been asked that question, and the
answer is not implied by the three sets of unit tests — it depends on how the
gates compose, which is a property of no single module.

So this file builds the loop. A ``CountingApi`` stands in for
``users().messages().send()`` and records every call it receives; the storm runs
for thousands of iterations doing exactly what a bug would do. The assertion is
the requirement: **zero calls reach the API once the gates have tripped**, and
the number that got through before that is small and accounted for.

The API here fails loudly rather than politely. A stand-in that quietly returned
success would let a broken Gatekeeper pass this file — the whole point is to
have something that can say "you sent me 4000 messages" at the end.

Nothing in this file touches a network, a credential or Google. The storm is
real; the endpoint is a list.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from thief_agent.infra.dos_detector import Detector, DosDetected
from thief_agent.infra.gatekeeper import Gatekeeper, Rejected
from thief_agent.infra.quota import Quota
from thief_agent.infra.report import Message, Report, Repositories, SubGameResult
from thief_agent.infra.token_bucket import Limiter, TokenBucket

STORM = 4000
"""Iterations of the loop. A bug does not get bored."""


class Clock:
    """Wall time as a runaway loop experiences it: barely moving."""

    def __init__(self, at: float = 1000.0, step: float = 0.002) -> None:
        self.at = at
        self.step = step

    def __call__(self) -> float:
        self.at += self.step
        return self.at


@dataclass
class CountingApi:
    """What ``users().messages().send()`` would be. Counts, and never forgives."""

    calls: list[dict[str, str]] = field(default_factory=list)

    def send(self, payload: dict[str, str]) -> None:
        self.calls.append(payload)

    @property
    def count(self) -> int:
        return len(self.calls)


def a_report() -> Report:
    return Report(
        game_id="uoh26-s82kma9e",
        role="thief",
        team="uoh26-thieves",
        opponent_team="uoh26-others",
        repositories=Repositories(
            cop_repo="https://github.com/Mhmdabad/police_agent",
            thief_repo="https://github.com/Mhmdabad/theif_agent",
            opponent_cop_repo="https://github.com/other/police",
            opponent_thief_repo="https://github.com/other/thief",
        ),
        sub_games=(SubGameResult(sub_game=1, cop_score=100, thief_score=0, commit_hash="a" * 40),),
        total_tokens=1234,
        agreed=True,
    )


def gatekeeper(tmp_path: Path, clock: Clock, limit: int = 50) -> Gatekeeper:
    return Gatekeeper(
        detector=Detector(path=tmp_path / ".locked_thief.json", now=clock),
        quota=Quota(
            path=tmp_path / ".quota_thief.json", limit=limit, now=lambda: datetime.now(UTC)
        ),
        limiter=Limiter(bucket=TokenBucket(capacity=2.0, per_minute=30.0, now=clock)),
    )


@dataclass
class Storm:
    """What happened when the loop ran."""

    attempts: int = 0
    sent: int = 0
    stopped_by: str = ""


def run_storm(gate: Gatekeeper, api: CountingApi, iterations: int = STORM) -> Storm:
    """The bug: send the report, forever, as fast as the loop goes round.

    Written the way a real defect would be — no error handling, no backoff, no
    awareness that anything might be wrong. It stops only because something
    stops it, and what stopped it is the result.
    """
    storm = Storm()
    payload = Message(report=a_report(), sender="thief@example.com").raw()
    for _ in range(iterations):
        storm.attempts += 1
        try:
            waited = gate.admit()
            if waited is not None:
                gate.release()
                continue
            gate.record_attempt()
            api.send(payload)
            storm.sent += 1
        except (Rejected, DosDetected) as exc:
            storm.stopped_by = type(exc).__name__
            return storm
    return storm


class TestTheStormIsStopped:
    def test_it_does_not_run_to_completion(self, tmp_path: Path) -> None:
        """4000 iterations, and something must refuse long before the end."""
        api = CountingApi()
        storm = run_storm(gatekeeper(tmp_path, Clock()), api)
        assert storm.stopped_by, "the loop ran 4000 times and nothing objected"
        assert storm.attempts < STORM

    def test_almost_nothing_reaches_the_api(self, tmp_path: Path) -> None:
        """The requirement, stated as a number."""
        api = CountingApi()
        run_storm(gatekeeper(tmp_path, Clock()), api)
        assert api.count <= 6, f"{api.count} messages reached the API"

    def test_nothing_reaches_the_api_after_the_gates_trip(self, tmp_path: Path) -> None:
        """'Zero API calls' is about what happens *after* — and it is zero."""
        api = CountingApi()
        clock = Clock()
        gate = gatekeeper(tmp_path, clock)
        run_storm(gate, api)
        reached = api.count

        for _ in range(500):
            with pytest.raises((Rejected, DosDetected)):
                if gate.admit() is None:
                    gate.record_attempt()
                    api.send({"raw": "x"})
        assert api.count == reached, "the pipeline reopened after tripping"

    def test_a_fresh_process_is_still_blocked(self, tmp_path: Path) -> None:
        """A crash loop restarts the process. The gates are on disk."""
        api = CountingApi()
        run_storm(gatekeeper(tmp_path, Clock()), api)
        reached = api.count

        restarted = gatekeeper(tmp_path, Clock())
        second = run_storm(restarted, api, iterations=500)
        assert second.sent == 0
        assert api.count == reached


class TestEachGateCanStopItAlone:
    """Defence in depth means no single gate is load-bearing."""

    def test_the_dos_detector_alone_stops_it(self, tmp_path: Path) -> None:
        api = CountingApi()
        clock = Clock()
        gate = gatekeeper(tmp_path, clock, limit=10_000)
        gate.limiter.bucket.capacity = 10_000.0
        gate.limiter.bucket._tokens = 10_000.0  # noqa: SLF001 - disabling the other gates
        storm = run_storm(gate, api)
        assert storm.stopped_by == "DosDetected"
        assert api.count < 10

    def test_the_quota_alone_stops_it(self, tmp_path: Path) -> None:
        api = CountingApi()
        clock = Clock()
        gate = gatekeeper(tmp_path, clock, limit=3)
        gate.detector.burst_limit = 10_000
        gate.detector.metronome_run = 10_000
        gate.limiter.bucket.capacity = 10_000.0
        gate.limiter.bucket._tokens = 10_000.0  # noqa: SLF001
        storm = run_storm(gate, api)
        assert storm.stopped_by == "Rejected"
        assert api.count == 3, "the ceiling is the ceiling"

    def test_the_bucket_alone_throttles_it(self, tmp_path: Path) -> None:
        """The bucket does not refuse — it makes the loop wait, forever."""
        api = CountingApi()
        gate = gatekeeper(tmp_path, Clock(step=0.0), limit=10_000)
        gate.detector.burst_limit = 10_000
        gate.detector.metronome_run = 10_000
        run_storm(gate, api, iterations=1000)
        assert api.count == 2, "only the initial burst capacity got through"


class TestTheAccountIsWorthMoreThanTheReport:
    def test_the_lock_names_what_it_saw(self, tmp_path: Path) -> None:
        api = CountingApi()
        gate = gatekeeper(tmp_path, Clock())
        run_storm(gate, api)
        assert gate.detector.locked
        assert gate.detector.reason(), "a lock with no reason tells nobody anything"

    def test_recovery_requires_a_person(self, tmp_path: Path) -> None:
        """FR-7.20's sacrifice: one report lost, deliberately, and it stays lost."""
        api = CountingApi()
        clock = Clock()
        gate = gatekeeper(tmp_path, clock)
        run_storm(gate, api)
        assert gate.detector.locked

        gate.detector.reset()
        gate.quota.reset()
        clock.at += 600.0  # and enough quiet time to have earned a token back
        assert run_storm(gate, api, iterations=50).sent > 0, "reset should restore service"


class TestTheStormIsRealistic:
    def test_the_payload_is_a_real_report(self, tmp_path: Path) -> None:
        """Not a stub — the storm sends what the agent would actually send."""
        api = CountingApi()
        run_storm(gatekeeper(tmp_path, Clock()), api)
        assert api.calls, "nothing was sent at all, so the test proves nothing"
        assert api.calls[0]["raw"], "the storm sent an empty payload"

    def test_the_loop_has_no_error_handling_of_its_own(self, tmp_path: Path) -> None:
        """A bug does not back off. Only the Gatekeeper stops this."""
        api = CountingApi()
        storm = run_storm(gatekeeper(tmp_path, Clock()), api)
        assert storm.stopped_by in {"Rejected", "DosDetected"}
