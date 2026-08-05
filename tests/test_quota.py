"""The daily ceiling, and the two ways an obvious implementation defeats it."""

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from thief_agent.infra.quota import (
    DAILY_LIMIT,
    QUOTA_PATH_ENV,
    Quota,
    QuotaError,
    QuotaExhausted,
    quota_path,
)

NOON = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


class Clock:
    """A clock a test can move, so day rollover is reachable without waiting."""

    def __init__(self, at: datetime = NOON) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> None:
        self.at += timedelta(**delta)


def quota(tmp_path: Path, limit: int = 3, clock: Clock | None = None) -> Quota:
    return Quota(path=tmp_path / ".quota_thief.json", limit=limit, now=clock or Clock())


class TestCountingAndTheCeiling:
    def test_a_fresh_ledger_starts_at_zero(self, tmp_path: Path) -> None:
        assert quota(tmp_path).used() == 0
        assert quota(tmp_path).remaining() == 3

    def test_reserving_increments(self, tmp_path: Path) -> None:
        gate = quota(tmp_path)
        assert gate.reserve() == 1
        assert gate.reserve() == 2
        assert gate.remaining() == 1

    def test_reserving_past_the_ceiling_is_refused(self, tmp_path: Path) -> None:
        gate = quota(tmp_path)
        for _ in range(3):
            gate.reserve()
        with pytest.raises(QuotaExhausted, match="3 of 3 sends used"):
            gate.reserve()

    def test_a_refused_reservation_does_not_burn_the_slot(self, tmp_path: Path) -> None:
        """Otherwise asking twice would cost what asking once did not buy."""
        gate = quota(tmp_path)
        gate.reserve(2)
        with pytest.raises(QuotaExhausted):
            gate.reserve(2)
        assert gate.used() == 2
        assert gate.reserve() == 3

    def test_a_multi_slot_reservation_is_all_or_nothing(self, tmp_path: Path) -> None:
        gate = quota(tmp_path)
        with pytest.raises(QuotaExhausted):
            gate.reserve(4)
        assert gate.used() == 0

    def test_check_reports_without_spending(self, tmp_path: Path) -> None:
        gate = quota(tmp_path)
        gate.check()
        assert gate.used() == 0

    def test_check_raises_once_the_ceiling_is_reached(self, tmp_path: Path) -> None:
        gate = quota(tmp_path)
        gate.reserve(3)
        with pytest.raises(QuotaExhausted, match="does not yield to a retry"):
            gate.check()

    def test_a_reservation_of_zero_is_a_mistake_not_a_no_op(self, tmp_path: Path) -> None:
        with pytest.raises(QuotaError, match="at least one send"):
            quota(tmp_path).reserve(0)


class TestTheCountSurvivesTheProcess:
    """The failure a quota manager exists to stop is a bug that keeps restarting."""

    def test_a_new_instance_sees_what_the_old_one_spent(self, tmp_path: Path) -> None:
        quota(tmp_path).reserve(2)
        assert quota(tmp_path).used() == 2, "an in-memory counter would read zero here"

    def test_a_crash_loop_cannot_reset_the_ceiling(self, tmp_path: Path) -> None:
        """Simulates the exact scenario FR-7.18 names: restart, send, repeat."""
        sent = 0
        for _ in range(20):
            gate = quota(tmp_path)  # a brand-new process each time
            try:
                gate.reserve()
            except QuotaExhausted:
                continue
            sent += 1
        assert sent == 3, f"the loop got {sent} sends out past a ceiling of 3"

    def test_the_ledger_is_readable_only_by_its_owner(self, tmp_path: Path) -> None:
        gate = quota(tmp_path)
        gate.reserve()
        assert stat.S_IMODE(gate.path.stat().st_mode) == 0o600


class TestReservingBeforeTheSendNotAfter:
    def test_a_send_that_fails_after_reserving_still_counts(self, tmp_path: Path) -> None:
        """Overcounting by one costs a report; undercounting costs the account."""
        gate = quota(tmp_path)
        gate.reserve()
        with pytest.raises(RuntimeError):
            raise RuntimeError("the API call blew up after the message went out")
        assert gate.used() == 1

    def test_counting_after_success_would_never_reach_the_ceiling(self, tmp_path: Path) -> None:
        """The bug this ordering avoids, written as an executable argument."""
        gate = quota(tmp_path)
        for _ in range(10):
            gate.check()  # a caller that only records on success
        assert gate.used() == 0, "checking without reserving spends nothing — hence reserve()"


class TestTheDayRollsOverInUtc:
    def test_a_new_day_starts_the_count_again(self, tmp_path: Path) -> None:
        clock = Clock()
        gate = quota(tmp_path, clock=clock)
        gate.reserve(3)
        clock.advance(days=1)
        assert gate.used() == 0
        assert gate.reserve() == 1

    def test_later_the_same_day_does_not_roll_over(self, tmp_path: Path) -> None:
        clock = Clock()
        gate = quota(tmp_path, clock=clock)
        gate.reserve(2)
        clock.advance(hours=11)
        assert gate.used() == 2

    def test_the_boundary_is_utc_midnight(self, tmp_path: Path) -> None:
        clock = Clock(datetime(2026, 8, 5, 23, 59, tzinfo=UTC))
        gate = quota(tmp_path, clock=clock)
        gate.reserve(3)
        clock.advance(minutes=2)
        assert gate.used() == 0, "a ceiling that moves with local time is wrong twice a year"

    def test_a_ledger_from_another_day_is_not_carried_forward(self, tmp_path: Path) -> None:
        path = tmp_path / ".quota_thief.json"
        path.write_text(json.dumps({"day": "2020-01-01", "used": 99}))
        assert quota(tmp_path).used() == 0


class TestAnUnreadableLedgerFailsClosed:
    """Corruption must not be a way to get an unlimited day."""

    def test_a_damaged_file_refuses_rather_than_assuming_zero(self, tmp_path: Path) -> None:
        path = tmp_path / ".quota_thief.json"
        path.write_text("{half a wr")
        with pytest.raises(QuotaError, match="cannot be read"):
            quota(tmp_path).used()

    def test_a_file_that_is_not_a_count_refuses(self, tmp_path: Path) -> None:
        path = tmp_path / ".quota_thief.json"
        path.write_text(json.dumps({"day": "2026-08-05", "used": "lots"}))
        with pytest.raises(QuotaError, match="not a count"):
            quota(tmp_path).used()

    def test_a_json_list_refuses(self, tmp_path: Path) -> None:
        path = tmp_path / ".quota_thief.json"
        path.write_text("[]")
        with pytest.raises(QuotaError, match="not a count"):
            quota(tmp_path).used()

    def test_a_directory_in_place_of_the_ledger_refuses(self, tmp_path: Path) -> None:
        (tmp_path / ".quota_thief.json").mkdir()
        with pytest.raises(QuotaError, match="cannot be read"):
            quota(tmp_path).used()

    def test_reserving_against_a_damaged_ledger_refuses_too(self, tmp_path: Path) -> None:
        """Not just reading — the send path must not proceed either."""
        (tmp_path / ".quota_thief.json").write_text("{half a wr")
        with pytest.raises(QuotaError):
            quota(tmp_path).reserve()

    def test_the_message_names_the_deliberate_remedy(self, tmp_path: Path) -> None:
        (tmp_path / ".quota_thief.json").write_text("{half a wr")
        with pytest.raises(QuotaError, match="clear it deliberately"):
            quota(tmp_path).used()

    def test_reset_clears_it_and_is_the_only_thing_that_does(self, tmp_path: Path) -> None:
        gate = quota(tmp_path)
        (tmp_path / ".quota_thief.json").write_text("{half a wr")
        gate.reset()
        assert gate.used() == 0


class TestWhereTheLedgerLives:
    def test_it_is_named_per_agent(self) -> None:
        assert quota_path("thief_agent", {}).name == ".quota_thief.json"
        assert quota_path("thief_agent", {}).name == ".quota_thief.json"

    def test_the_environment_overrides_it(self) -> None:
        assert quota_path("thief_agent", {QUOTA_PATH_ENV: "/tmp/q.json"}) == Path("/tmp/q.json")

    def test_it_reads_the_real_environment_when_none_is_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(QUOTA_PATH_ENV, "/tmp/from-env.json")
        assert quota_path("thief_agent") == Path("/tmp/from-env.json")


class TestTheDefaultCeiling:
    def test_it_is_well_below_anything_google_enforces(self) -> None:
        """A threshold just under the provider's does not protect anything."""
        assert DAILY_LIMIT == 50
        assert DAILY_LIMIT < 500, "the free-tier recipient limit is an order of magnitude up"

    def test_it_leaves_room_for_the_league(self) -> None:
        """One report per legal match, at most ten games per team."""
        assert DAILY_LIMIT > 10 * 2

    def test_the_default_is_used_when_no_limit_is_given(self, tmp_path: Path) -> None:
        assert Quota(path=tmp_path / "q.json").limit == DAILY_LIMIT


class TestStatusIsSafeToPrint:
    def test_it_reads_as_a_sentence(self, tmp_path: Path) -> None:
        gate = quota(tmp_path)
        gate.reserve()
        assert gate.status() == "1/3 sends used on 2026-08-05 UTC"

    def test_it_does_not_raise_on_a_damaged_ledger(self, tmp_path: Path) -> None:
        """A status line is what an operator reads while diagnosing the damage."""
        (tmp_path / ".quota_thief.json").write_text("{half a wr")
        assert "blocked" in quota(tmp_path).status()
