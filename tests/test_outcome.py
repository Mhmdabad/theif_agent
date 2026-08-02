"""Tests for sub-game termination conditions."""

from thief_agent.domain.actions import PlaceBarrier, apply_action
from thief_agent.domain.axes import ORIGIN_CORNERS, AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.outcome import (
    DEFAULT_SURVIVAL_THRESHOLD,
    is_capture_by_overlap,
    is_enclosure_capture,
    is_survival,
    is_trapping_capture,
)
from thief_agent.domain.rules import advance_turn, apply_move, legal_moves

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


class TestEnclosureCapture:
    def test_open_board_is_not_enclosure(self) -> None:
        assert not is_enclosure_capture(make(), AXES)

    def test_all_four_neighbours_sealed_is_capture(self) -> None:
        state = make(thief=(3, 3), barriers=frozenset({(2, 3), (4, 3), (3, 2), (3, 4)}))
        assert is_enclosure_capture(state, AXES)

    def test_three_sealed_is_not_yet(self) -> None:
        state = make(thief=(3, 3), barriers=frozenset({(2, 3), (4, 3), (3, 2)}))
        assert not is_enclosure_capture(state, AXES)

    def test_board_edges_count_as_walls(self) -> None:
        """A cornered thief needs two barriers, not four."""
        state = make(cop=(6, 6), thief=(0, 0), barriers=frozenset({(1, 0), (0, 1)}))
        assert is_enclosure_capture(state, AXES)

    def test_edge_thief_needs_three(self) -> None:
        state = make(cop=(6, 6), thief=(0, 3), barriers=frozenset({(0, 2), (0, 4), (1, 3)}))
        assert is_enclosure_capture(state, AXES)

    def test_stay_remains_legal_under_enclosure(self) -> None:
        """Why the condition is over neighbours, not the move list."""
        state = make(thief=(3, 3), barriers=frozenset({(2, 3), (4, 3), (3, 2), (3, 4)}))
        assert legal_moves(state, "thief", AXES) == ["STAY"]
        assert is_enclosure_capture(state, AXES)

    def test_a_literal_reading_would_never_fire(self) -> None:
        """The move list is never empty while the thief's own cell is free."""
        state = make(thief=(3, 3), barriers=frozenset({(2, 3), (4, 3), (3, 2), (3, 4)}))
        assert legal_moves(state, "thief", AXES) != []

    def test_holds_under_every_axis_convention(self) -> None:
        state = make(thief=(3, 3), barriers=frozenset({(2, 3), (4, 3), (3, 2), (3, 4)}))
        for corner in ORIGIN_CORNERS:
            assert is_enclosure_capture(state, AxisConvention(origin_corner=corner))

    def test_is_independent_of_the_other_captures(self) -> None:
        state = make(cop=(0, 0), thief=(3, 3), barriers=frozenset({(2, 3), (4, 3), (3, 2), (3, 4)}))
        assert is_enclosure_capture(state, AXES)
        assert not is_capture_by_overlap(state)
        assert not is_trapping_capture(state)


class TestSurvival:
    def test_default_threshold_matches_appendix_f(self) -> None:
        assert DEFAULT_SURVIVAL_THRESHOLD == 35

    def test_not_survived_before_the_threshold(self) -> None:
        assert not is_survival(make(step=34), AXES)

    def test_survived_at_the_threshold(self) -> None:
        assert is_survival(make(step=35), AXES)

    def test_survived_beyond_the_threshold(self) -> None:
        assert is_survival(make(step=40), AXES)

    def test_threshold_is_raisable_by_agreement(self) -> None:
        assert not is_survival(make(step=35), AXES, survival_threshold=50)
        assert is_survival(make(step=50), AXES, survival_threshold=50)

    def test_capture_by_overlap_denies_survival(self) -> None:
        """Reaching the count while standing under the cop is not a win."""
        assert not is_survival(make(cop=(3, 3), thief=(3, 3), step=40), AXES)

    def test_trapping_capture_denies_survival(self) -> None:
        state = make(thief=(3, 3), barriers=frozenset({(3, 3)}), step=40)
        assert not is_survival(state, AXES)

    def test_enclosure_capture_denies_survival(self) -> None:
        walls = frozenset({(2, 3), (4, 3), (3, 2), (3, 4)})
        assert not is_survival(make(thief=(3, 3), barriers=walls, step=40), AXES)

    def test_counts_full_turns_not_half_moves(self) -> None:
        """apply_move must not advance the count, or survival arrives early."""
        state = make(step=34)
        state = apply_move(state, "cop", "S", AXES)
        state = apply_move(state, "thief", "N", AXES)
        assert not is_survival(state, AXES)
        assert is_survival(advance_turn(state), AXES)
