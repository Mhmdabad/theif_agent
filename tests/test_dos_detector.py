"""Telling a bug from a busy day, and refusing to reopen the door on it."""

import contextlib
import json
import stat
from pathlib import Path

import pytest

from thief_agent.infra.dos_detector import (
    BURST_LIMIT,
    LOCK_PATH_ENV,
    METRONOME_RUN,
    Detector,
    DosDetected,
    lock_path,
)


class Clock:
    def __init__(self, at: float = 1000.0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += seconds


def detector(tmp_path: Path, clock: Clock | None = None) -> Detector:
    return Detector(path=tmp_path / ".locked_thief.json", now=clock or Clock())


def realistic(gate: Detector, clock: Clock, count: int = 10) -> None:
    """Sends at a match's pace: minutes apart, and irregular."""
    for gap in ([600.0, 431.0, 907.0, 1200.0, 522.0] * 4)[:count]:
        clock.advance(gap)
        gate.record()


class TestOrdinaryUseDoesNotTrip:
    def test_a_single_send_is_fine(self, tmp_path: Path) -> None:
        gate = detector(tmp_path)
        gate.record()
        assert not gate.locked

    def test_a_match_worth_of_reports_is_fine(self, tmp_path: Path) -> None:
        """One report per game, ten games, irregular gaps. The real workload."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        realistic(gate, clock, count=10)
        assert not gate.locked

    def test_a_few_sends_close_together_are_fine(self, tmp_path: Path) -> None:
        """A re-run, a retry, a second agent. Under the burst limit."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        for gap in (3.0, 11.0, 2.0):
            clock.advance(gap)
            gate.record()
        assert not gate.locked

    def test_the_burst_window_slides(self, tmp_path: Path) -> None:
        """Sends age out, so a long steady day is not retroactively a burst."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        for gap in (90.0, 140.0, 71.0, 205.0, 96.0, 133.0, 88.0):
            clock.advance(gap)
            gate.record()
        assert not gate.locked


class TestTheBurstTrigger:
    def test_too_many_inside_the_window_locks(self, tmp_path: Path) -> None:
        clock = Clock()
        gate = detector(tmp_path, clock)
        with pytest.raises(DosDetected, match="over the burst limit"):
            for gap in (1.0, 4.0, 2.0, 9.0, 1.0, 5.0):
                clock.advance(gap)
                gate.record()

    def test_the_limit_is_far_under_what_the_bucket_would_allow(self) -> None:
        """Gate two permits 30/minute. Volume alone is not the signal."""
        assert BURST_LIMIT < 30

    def test_the_lock_survives_the_object(self, tmp_path: Path) -> None:
        clock = Clock()
        gate = detector(tmp_path, clock)
        with pytest.raises(DosDetected):
            for gap in (1.0, 4.0, 2.0, 9.0, 1.0, 5.0):
                clock.advance(gap)
                gate.record()
        assert detector(tmp_path).locked, "a fresh process must still find the door shut"


class TestTheMetronomeTrigger:
    def test_perfectly_even_spacing_locks(self, tmp_path: Path) -> None:
        """A loop's cadence. Slow enough that the burst rule never fires."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        with pytest.raises(DosDetected, match="a loop's cadence"):
            for _ in range(METRONOME_RUN + 1):
                clock.advance(30.0)
                gate.record()

    def test_it_is_regularity_not_volume(self, tmp_path: Path) -> None:
        """Five sends over four minutes is not a burst by any measure."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        with pytest.raises(DosDetected) as raised:
            for _ in range(METRONOME_RUN + 1):
                clock.advance(45.0)
                gate.record()
        assert "burst limit" not in str(raised.value)

    def test_a_slow_relentless_loop_is_caught(self, tmp_path: Path) -> None:
        """The case the cadence rule exists for, and the burst rule cannot see.

        One send every five minutes, forever. Never more than one inside the
        burst window, so gate two and the burst rule both wave it through — and
        it would still empty the daily quota by lunchtime. Only the *shape*
        gives it away.
        """
        clock = Clock()
        gate = detector(tmp_path, clock)
        with pytest.raises(DosDetected, match="cadence"):
            for _ in range(METRONOME_RUN + 1):
                clock.advance(300.0)
                gate.record()

    def test_the_cadence_history_outlives_the_burst_window(self, tmp_path: Path) -> None:
        """Windowing the history before measuring shape would blind the rule."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        clock.advance(300.0)
        gate.record()
        clock.advance(300.0)
        gate.record()
        assert len(gate.recent) == 2, "both are older than the 60s burst window"

    def test_irregular_spacing_at_the_same_volume_does_not_lock(self, tmp_path: Path) -> None:
        """The control: same number of sends, human-shaped gaps."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        for gap in (30.0, 44.0, 31.0, 90.0, 37.0):
            clock.advance(gap)
            gate.record()
        assert not gate.locked

    def test_a_run_one_short_does_not_lock(self, tmp_path: Path) -> None:
        clock = Clock()
        gate = detector(tmp_path, clock)
        for _ in range(METRONOME_RUN):
            clock.advance(45.0)
            gate.record()
        assert not gate.locked

    def test_a_small_jitter_is_still_mechanical(self, tmp_path: Path) -> None:
        """Real code has some jitter; five percent of it is not a person."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        with pytest.raises(DosDetected, match="cadence"):
            for gap in (45.0, 45.4, 44.8, 45.2, 45.1):
                clock.advance(gap)
                gate.record()

    def test_sends_in_the_same_instant_are_mechanical(self, tmp_path: Path) -> None:
        """Nothing human sends twice at the same moment, let alone five times."""
        gate = detector(tmp_path, Clock())
        with pytest.raises(DosDetected):
            for _ in range(METRONOME_RUN + 1):
                gate.record()


class TestTheLockDoesNotExpire:
    def test_check_keeps_refusing_however_long_you_wait(self, tmp_path: Path) -> None:
        """A half-open circuit breaker is right for a flaky dependency.

        It is wrong here: the fault is ours, the loop is still running, and
        reopening the door hands it the account again.
        """
        clock = Clock()
        gate = detector(tmp_path, clock)
        with pytest.raises(DosDetected):
            for gap in (1.0, 4.0, 2.0, 9.0, 1.0, 5.0):
                clock.advance(gap)
                gate.record()
        clock.advance(86_400.0)
        with pytest.raises(DosDetected, match="is locked"):
            gate.check()

    def test_recording_while_locked_refuses(self, tmp_path: Path) -> None:
        (tmp_path / ".locked_thief.json").write_text(json.dumps({"reason": "earlier"}))
        with pytest.raises(DosDetected):
            detector(tmp_path).record()

    def test_only_reset_clears_it(self, tmp_path: Path) -> None:
        gate = detector(tmp_path)
        (tmp_path / ".locked_thief.json").write_text(json.dumps({"reason": "earlier"}))
        gate.reset()
        assert not gate.locked
        gate.record()

    def test_reset_also_forgets_the_history(self, tmp_path: Path) -> None:
        """Otherwise the first send after a reset re-trips on stale timestamps."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        with pytest.raises(DosDetected):
            for gap in (1.0, 4.0, 2.0, 9.0, 1.0, 5.0):
                clock.advance(gap)
                gate.record()
        gate.reset()
        clock.advance(1.0)
        gate.record()
        assert not gate.locked

    def test_reset_on_an_unlocked_detector_is_harmless(self, tmp_path: Path) -> None:
        detector(tmp_path).reset()


class TestTheLockExplainsItself:
    def test_it_records_why(self, tmp_path: Path) -> None:
        clock = Clock()
        gate = detector(tmp_path, clock)
        with pytest.raises(DosDetected):
            for gap in (1.0, 4.0, 2.0, 9.0, 1.0, 5.0):
                clock.advance(gap)
                gate.record()
        assert "burst limit" in gate.reason()

    def test_the_exception_names_the_file_to_delete(self, tmp_path: Path) -> None:
        clock = Clock()
        gate = detector(tmp_path, clock)
        with pytest.raises(DosDetected, match=r"delete .*\.locked_thief\.json"):
            for gap in (1.0, 4.0, 2.0, 9.0, 1.0, 5.0):
                clock.advance(gap)
                gate.record()

    def test_it_says_a_report_is_being_sacrificed(self, tmp_path: Path) -> None:
        """FR-7.20's own framing, so the reader knows this was the plan."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        with pytest.raises(DosDetected, match="sacrificed to save the account"):
            for gap in (1.0, 4.0, 2.0, 9.0, 1.0, 5.0):
                clock.advance(gap)
                gate.record()

    def test_an_unreadable_lock_file_still_reads_as_locked(self, tmp_path: Path) -> None:
        """The lock is the file existing, not the file parsing."""
        (tmp_path / ".locked_thief.json").write_text("{half a wr")
        gate = detector(tmp_path)
        assert gate.locked
        assert "could not be read" in gate.reason()
        with pytest.raises(DosDetected):
            gate.check()

    def test_a_lock_file_that_is_not_an_object_still_locks(self, tmp_path: Path) -> None:
        (tmp_path / ".locked_thief.json").write_text("[]")
        assert detector(tmp_path).reason() == ""
        with pytest.raises(DosDetected):
            detector(tmp_path).check()

    def test_the_lock_file_is_owner_only(self, tmp_path: Path) -> None:
        clock = Clock()
        gate = detector(tmp_path, clock)
        with pytest.raises(DosDetected):
            for gap in (1.0, 4.0, 2.0, 9.0, 1.0, 5.0):
                clock.advance(gap)
                gate.record()
        assert stat.S_IMODE(gate.path.stat().st_mode) == 0o600


class TestItWatchesAttemptsNotSuccesses:
    def test_a_loop_that_fails_every_time_is_still_caught(self, tmp_path: Path) -> None:
        """The loop most likely to be running is the one that keeps failing."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        caught = 0
        for gap in (1.0, 4.0, 2.0, 9.0, 1.0, 5.0):
            clock.advance(gap)
            try:
                gate.record()
            except DosDetected:
                caught += 1
                break
            caught += 0
        assert caught == 1 and gate.locked

    def test_the_lock_is_written_before_the_exception(self, tmp_path: Path) -> None:
        """A caller that swallows the exception still finds the door shut."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        for gap in (1.0, 4.0, 2.0, 9.0, 1.0, 5.0):
            clock.advance(gap)
            with contextlib.suppress(DosDetected):
                gate.record()
        assert detector(tmp_path).locked


class TestTheHistoryIsBounded:
    def test_it_does_not_grow_without_limit(self, tmp_path: Path) -> None:
        """A long-running agent must not accumulate timestamps forever."""
        clock = Clock()
        gate = detector(tmp_path, clock)
        for index in range(200):
            clock.advance(600.0 + (index % 7) * 97.0)
            gate.record()
        assert len(gate.recent) <= gate.history


class TestWhereTheLockLives:
    def test_it_is_named_per_agent(self) -> None:
        assert lock_path("thief_agent", {}).name == ".locked_thief.json"
        assert lock_path("thief_agent", {}).name == ".locked_thief.json"

    def test_the_environment_overrides_it(self) -> None:
        assert lock_path("thief_agent", {LOCK_PATH_ENV: "/tmp/l.json"}) == Path("/tmp/l.json")

    def test_it_reads_the_real_environment_when_none_is_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(LOCK_PATH_ENV, "/tmp/from-env.json")
        assert lock_path("thief_agent") == Path("/tmp/from-env.json")
