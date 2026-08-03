"""Tests for turn alternation."""

import pytest

from thief_agent.domain.board import Agent
from thief_agent.runtime.scheduler import OutOfTurnError, TurnScheduler


class TestAlternation:
    def test_the_cop_moves_first_by_default(self) -> None:
        assert TurnScheduler().to_move == "cop"

    def test_the_turn_passes_after_a_move(self) -> None:
        scheduler = TurnScheduler()
        scheduler.record("cop")
        assert scheduler.to_move == "thief"

    def test_sides_alternate_indefinitely(self) -> None:
        scheduler = TurnScheduler()
        expected: list[Agent] = ["cop", "thief"] * 20
        for agent in expected:
            assert scheduler.to_move == agent
            scheduler.record(agent)

    def test_the_first_mover_is_configurable(self) -> None:
        """Start positions are negotiable, so move order may be too."""
        assert TurnScheduler(first="thief").to_move == "thief"


class TestOutOfTurn:
    def test_acting_out_of_turn_raises(self) -> None:
        with pytest.raises(OutOfTurnError, match="thief acted out of turn"):
            TurnScheduler().record("thief")

    def test_the_error_names_who_was_owed_the_turn(self) -> None:
        with pytest.raises(OutOfTurnError, match="cop is to move"):
            TurnScheduler().record("thief")

    def test_moving_twice_in_a_row_is_refused(self) -> None:
        scheduler = TurnScheduler()
        scheduler.record("cop")
        with pytest.raises(OutOfTurnError):
            scheduler.record("cop")

    def test_a_refused_move_does_not_advance_anything(self) -> None:
        scheduler = TurnScheduler()
        with pytest.raises(OutOfTurnError):
            scheduler.record("thief")
        assert (scheduler.half_moves, scheduler.completed_turns) == (0, 0)
        assert scheduler.to_move == "cop"

    def test_require_turn_checks_without_recording(self) -> None:
        scheduler = TurnScheduler()
        scheduler.require_turn("cop")
        assert scheduler.half_moves == 0


class TestFullTurnBoundary:
    def test_one_half_move_is_not_a_full_turn(self) -> None:
        assert TurnScheduler().record("cop") is False

    def test_both_sides_moving_completes_a_turn(self) -> None:
        scheduler = TurnScheduler()
        scheduler.record("cop")
        assert scheduler.record("thief") is True

    def test_the_boundary_repeats_every_two_half_moves(self) -> None:
        scheduler = TurnScheduler()
        order: list[Agent] = ["cop", "thief"] * 5
        boundaries = [scheduler.record(agent) for agent in order]
        assert boundaries == [False, True] * 5

    def test_completed_turns_counts_full_turns_only(self) -> None:
        """A half-move counter would decay scent twice as fast."""
        scheduler = TurnScheduler()
        order: list[Agent] = ["cop", "thief"] * 35
        for agent in order:
            scheduler.record(agent)
        assert scheduler.half_moves == 70
        assert scheduler.completed_turns == 35

    def test_a_survival_length_series_yields_the_expected_count(self) -> None:
        scheduler = TurnScheduler()
        while scheduler.completed_turns < 35:
            scheduler.record(scheduler.to_move)
        assert scheduler.completed_turns == 35
        assert scheduler.half_moves == 70
