"""Tests for the hint throttle (#69) and token metering (#70)."""

import pytest

from thief_agent.domain.bluff import Bluff
from thief_agent.domain.budgeting import (
    DEADLINE_SECONDS,
    ESTIMATED_TOKENS_PER_CALL,
    EVERY_N_STEPS,
    TOKEN_BUDGET,
    Ration,
)
from thief_agent.domain.providers import Bluffer
from thief_agent.shared.appendix_f import TABLE, Status

HINT = Bluff(intent="truth", text="heading south past the docks", about=(5, 1))


def working(monkeypatch: pytest.MonkeyPatch, reply: str = "rephrased line") -> Bluffer:
    """An ollama provider with the transport faked. No real call is made."""
    bluffer = Bluffer(provider="ollama")
    monkeypatch.setattr(bluffer, "_ollama", lambda _: reply)
    return bluffer


class TestTheThrottle:
    def test_it_calls_only_every_nth_turn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ration = Ration(working(monkeypatch))
        for step in range(9):
            ration.speak(HINT, step)
        assert ration.bluffer.calls == 3
        assert ration.skipped == 6

    def test_a_skipped_turn_still_sends_a_complete_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not a degraded hint — the composed template line is legal and
        within the cap."""
        ration = Ration(working(monkeypatch))
        assert ration.speak(HINT, step=1) == HINT.text

    def test_it_is_what_makes_a_paid_provider_affordable(self) -> None:
        """35 turns x 6 sub-games at every turn exceeds the series budget;
        at every third it fits."""
        turns = 35 * 6
        assert turns * ESTIMATED_TOKENS_PER_CALL > TOKEN_BUDGET
        assert (turns // EVERY_N_STEPS) * ESTIMATED_TOKENS_PER_CALL < TOKEN_BUDGET

    def test_the_template_provider_is_never_throttled_because_it_never_calls(
        self,
    ) -> None:
        ration = Ration(Bluffer())
        for step in range(9):
            ration.speak(HINT, step)
        assert ration.bluffer.calls == 0 and ration.spent == 0


class TestTheDeadline:
    def test_it_matches_the_step_deadline(self) -> None:
        assert DEADLINE_SECONDS == 30.0

    def test_a_late_reply_is_discarded_for_the_template_line(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A turn that goes unanswered is a technical loss worth zero to both
        sides — strictly worse than the dullest hint."""
        ration = Ration(working(monkeypatch), deadline=0.0)
        assert ration.speak(HINT, step=0) == HINT.text
        assert ration.late == 1

    def test_a_prompt_reply_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ration = Ration(working(monkeypatch))
        assert ration.speak(HINT, step=0) == "rephrased line"
        assert ration.late == 0

    def test_a_late_call_is_still_paid_for(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The tokens were spent whether or not we used the answer."""
        ration = Ration(working(monkeypatch), deadline=0.0)
        ration.speak(HINT, step=0)
        assert ration.spent == ESTIMATED_TOKENS_PER_CALL


class TestTheMeter:
    def test_the_budget_is_read_from_appendix_f(self) -> None:
        row = next(r for r in TABLE if r.key == "token_budget_per_series")
        assert (TOKEN_BUDGET, row.status) == (200000, Status.NEGOTIABLE)

    def test_spending_is_counted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ration = Ration(working(monkeypatch))
        for step in (0, 3, 6):
            ration.speak(HINT, step)
        assert ration.spent == 3 * ESTIMATED_TOKENS_PER_CALL
        assert ration.remaining == TOKEN_BUDGET - ration.spent

    def test_the_estimate_is_deliberately_high(self) -> None:
        """Under-counting spends a budget we have already agreed, and being
        caught over it at audit is worse than sending template lines."""
        assert ESTIMATED_TOKENS_PER_CALL >= 1000

    def test_exhaustion_drops_to_template_permanently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hard stop, not a warning. A series can never fail for want of
        tokens."""
        ration = Ration(working(monkeypatch), budget=2 * ESTIMATED_TOKENS_PER_CALL)
        ration.speak(HINT, 0)
        ration.speak(HINT, 3)
        assert ration.exhausted
        assert ration.bluffer.provider == "template"

    def test_it_stays_stopped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ration = Ration(working(monkeypatch), budget=ESTIMATED_TOKENS_PER_CALL)
        ration.speak(HINT, 0)
        before = ration.bluffer.calls
        for step in range(3, 30, 3):
            assert ration.speak(HINT, step) == HINT.text
        assert ration.bluffer.calls == before

    def test_it_never_overspends(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The property the whole module exists for."""
        ration = Ration(working(monkeypatch), budget=10 * ESTIMATED_TOKENS_PER_CALL)
        for step in range(0, 600, 3):
            ration.speak(HINT, step)
            assert ration.spent <= ration.budget

    def test_a_budget_too_small_for_one_call_never_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ration = Ration(working(monkeypatch), budget=10)
        ration.speak(HINT, 0)
        assert ration.bluffer.calls == 0 and ration.spent == 0

    def test_stopping_twice_is_harmless(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ration = Ration(working(monkeypatch))
        ration.stop("first")
        ration.stop("second")
        assert ration.exhausted

    def test_it_reports_for_the_audit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ration = Ration(working(monkeypatch))
        ration.speak(HINT, 0)
        ration.speak(HINT, 1)
        assert "tokens" in str(ration) and "throttled" in str(ration)


class TestNothingHereLosesAMatch:
    def test_a_broken_provider_still_yields_a_hint(self) -> None:
        ration = Ration(Bluffer(provider="ollama", endpoint="http://localhost:1", timeout=0.1))
        assert ration.speak(HINT, step=0) == HINT.text

    def test_a_full_series_always_produces_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ration = Ration(working(monkeypatch), budget=3 * ESTIMATED_TOKENS_PER_CALL)
        for step in range(35 * 6):
            assert ration.speak(HINT, step).strip()
