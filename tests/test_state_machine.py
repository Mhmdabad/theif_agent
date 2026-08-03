"""Tests for the turn phase machine."""

import itertools

import pytest

from thief_agent.runtime.state_machine import (
    TRANSITIONS,
    GamePhaseMachine,
    IllegalTransitionError,
    Phase,
)

FULL_TURN = [
    Phase.COMPUTING_MOVE,
    Phase.COMMITTING,
    Phase.AWAITING_REVEAL,
    Phase.VERIFYING,
    Phase.WAITING_FOR_OPPONENT,
]


class TestTable:
    def test_every_phase_has_an_entry(self) -> None:
        assert set(TRANSITIONS) == set(Phase)

    def test_technical_loss_is_terminal(self) -> None:
        assert TRANSITIONS[Phase.TECHNICAL_LOSS] == frozenset()

    def test_every_communication_phase_can_fail(self) -> None:
        """Any phase that waits on the opponent must have an escape."""
        for phase in (
            Phase.COMPUTING_MOVE,
            Phase.COMMITTING,
            Phase.AWAITING_REVEAL,
            Phase.VERIFYING,
        ):
            assert Phase.TECHNICAL_LOSS in TRANSITIONS[phase]

    def test_the_cycle_returns_to_the_start(self) -> None:
        assert Phase.WAITING_FOR_OPPONENT in TRANSITIONS[Phase.VERIFYING]


class TestLegalCycle:
    def test_a_full_turn_walks_the_cycle(self) -> None:
        machine = GamePhaseMachine()
        for phase in FULL_TURN:
            machine.to(phase)
        assert machine.phase is Phase.WAITING_FOR_OPPONENT

    def test_many_turns_cycle_cleanly(self) -> None:
        machine = GamePhaseMachine()
        for _ in range(35):
            for phase in FULL_TURN:
                machine.to(phase)
        assert machine.phase is Phase.WAITING_FOR_OPPONENT
        assert len(machine.history) == 35 * 5 + 1

    def test_starts_waiting(self) -> None:
        assert GamePhaseMachine().phase is Phase.WAITING_FOR_OPPONENT


class TestIllegalTransitions:
    def test_skipping_commit_is_refused(self) -> None:
        """Revealing without committing is the fraud Commit-Reveal prevents."""
        machine = GamePhaseMachine()
        machine.to(Phase.COMPUTING_MOVE)
        with pytest.raises(IllegalTransitionError, match="computing_move -> awaiting_reveal"):
            machine.to(Phase.AWAITING_REVEAL)

    def test_acting_out_of_turn_is_refused(self) -> None:
        machine = GamePhaseMachine()
        with pytest.raises(IllegalTransitionError, match="-> committing"):
            machine.to(Phase.COMMITTING)

    def test_the_error_lists_the_legal_options(self) -> None:
        machine = GamePhaseMachine()
        with pytest.raises(IllegalTransitionError, match=r"legal from here: \['computing_move'\]"):
            machine.to(Phase.VERIFYING)

    @pytest.mark.parametrize(("source", "target"), list(itertools.product(Phase, Phase)))
    def test_only_table_entries_are_accepted(self, source: Phase, target: Phase) -> None:
        """Exhaustive over all 36 pairs, so no stray edge exists."""
        machine = GamePhaseMachine(source)
        if target in TRANSITIONS[source]:
            assert machine.to(target) is target
        else:
            with pytest.raises(IllegalTransitionError):
                machine.to(target)

    def test_a_failed_transition_does_not_change_phase(self) -> None:
        machine = GamePhaseMachine()
        with pytest.raises(IllegalTransitionError):
            machine.to(Phase.VERIFYING)
        assert machine.phase is Phase.WAITING_FOR_OPPONENT


class TestTerminal:
    def test_nothing_follows_a_technical_loss(self) -> None:
        machine = GamePhaseMachine(Phase.TECHNICAL_LOSS)
        assert machine.is_terminal
        for target in Phase:
            with pytest.raises(IllegalTransitionError):
                machine.to(target)

    def test_abort_works_from_every_live_phase(self) -> None:
        for phase in Phase:
            if phase is Phase.TECHNICAL_LOSS:
                continue
            machine = GamePhaseMachine(phase)
            assert machine.abort("tunnel dropped") is Phase.TECHNICAL_LOSS

    def test_abort_is_refused_once_terminal(self) -> None:
        machine = GamePhaseMachine(Phase.TECHNICAL_LOSS)
        with pytest.raises(IllegalTransitionError, match="already terminal"):
            machine.abort("again")

    def test_abort_is_greppable_in_history(self) -> None:
        machine = GamePhaseMachine()
        machine.to(Phase.COMPUTING_MOVE)
        machine.abort("timeout")
        assert machine.history[-1] is Phase.TECHNICAL_LOSS


class TestCan:
    def test_reports_without_transitioning(self) -> None:
        machine = GamePhaseMachine()
        assert machine.can(Phase.COMPUTING_MOVE)
        assert not machine.can(Phase.VERIFYING)
        assert machine.phase is Phase.WAITING_FOR_OPPONENT
