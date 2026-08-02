"""Tests for sub-game termination conditions."""

from thief_agent.domain.actions import PlaceBarrier, apply_action
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.outcome import is_capture_by_overlap, is_trapping_capture
from thief_agent.domain.rules import apply_move, legal_moves

AXES = AxisConvention()


def make(**kw: object) -> BoardState:
    base: dict[str, object] = {"grid_size": 7, "cop": (0, 0), "thief": (3, 3)}
    base.update(kw)
    return BoardState(**base)  # type: ignore[arg-type]


class TestCaptureByOverlap:
    def test_separated_agents_are_not_a_capture(self) -> None:
        assert not is_capture_by_overlap(make())

    def test_same_cell_is_a_capture(self) -> None:
        assert is_capture_by_overlap(make(cop=(3, 3), thief=(3, 3)))

    def test_adjacent_is_not_a_capture(self) -> None:
        assert not is_capture_by_overlap(make(cop=(3, 2), thief=(3, 3)))

    def test_cop_moving_onto_the_thief_captures(self) -> None:
        after = apply_move(make(cop=(3, 2), thief=(3, 3)), "cop", "E", AXES)
        assert is_capture_by_overlap(after)

    def test_thief_moving_onto_the_cop_also_overlaps(self) -> None:
        """Overlap is symmetric: a thief that walks into the cop is caught."""
        after = apply_move(make(cop=(2, 3), thief=(3, 3)), "thief", "N", AXES)
        assert is_capture_by_overlap(after)

    def test_is_independent_of_barriers_and_step(self) -> None:
        state = make(cop=(1, 1), thief=(1, 1), barriers=frozenset({(5, 5)}), step=9)
        assert is_capture_by_overlap(state)

    def test_derived_from_state_not_from_a_claim(self) -> None:
        """No argument can assert a capture that the board does not show."""
        assert not is_capture_by_overlap(make(cop=(0, 0), thief=(6, 6)))


class TestTrappingCapture:
    def test_open_cell_is_not_a_trapping_capture(self) -> None:
        assert not is_trapping_capture(make())

    def test_barrier_under_the_thief_is_a_capture(self) -> None:
        assert is_trapping_capture(make(thief=(3, 3), barriers=frozenset({(3, 3)})))

    def test_barriers_elsewhere_do_not_trigger_it(self) -> None:
        state = make(thief=(3, 3), barriers=frozenset({(2, 3), (4, 3), (3, 2), (3, 4)}))
        assert not is_trapping_capture(state)

    def test_arises_from_a_real_placement(self) -> None:
        """Cop adjacent to the thief seals the thief's own cell."""
        state = make(cop=(3, 2), thief=(3, 3))
        after = apply_action(state, "cop", PlaceBarrier((3, 3)), AXES)
        assert is_trapping_capture(after)

    def test_needs_the_cop_adjacent(self) -> None:
        """Reach limits how the trap can be sprung, once #152 lands."""
        assert (3, 3) not in {(0, 0), (1, 0), (0, 1)}

    def test_a_thief_can_never_move_onto_a_barrier(self) -> None:
        """So standing on one always means it was sealed underneath."""
        state = make(thief=(3, 3), barriers=frozenset({(2, 3)}))
        assert "N" not in legal_moves(state, "thief", AXES)

    def test_is_independent_of_overlap(self) -> None:
        state = make(cop=(0, 0), thief=(3, 3), barriers=frozenset({(3, 3)}))
        assert is_trapping_capture(state)
        assert not is_capture_by_overlap(state)
