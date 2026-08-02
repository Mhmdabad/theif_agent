"""Tests for sub-game termination conditions."""

from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.outcome import is_capture_by_overlap
from thief_agent.domain.rules import apply_move

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
