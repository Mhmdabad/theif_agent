"""Tests for reachability over the open board."""

import pytest

from thief_agent.domain.axes import ORIGIN_CORNERS, AxisConvention, OriginCorner
from thief_agent.domain.board import BoardState
from thief_agent.domain.search import is_connected, reachable, reachable_area

AXES = AxisConvention()


def make(**kw: object) -> BoardState:
    base: dict[str, object] = {"grid_size": 7, "cop": (0, 0), "thief": (3, 3)}
    base.update(kw)
    return BoardState(**base)  # type: ignore[arg-type]


class TestReachable:
    def test_open_board_reaches_every_cell(self) -> None:
        assert reachable_area(make(), (0, 0), AXES) == 49

    def test_barriers_reduce_the_area(self) -> None:
        state = make(barriers=frozenset({(1, 1), (2, 2)}))
        assert reachable_area(state, (0, 0), AXES) == 47

    def test_includes_the_origin(self) -> None:
        assert (3, 3) in reachable(make(), (3, 3), AXES)

    def test_never_includes_a_barrier(self) -> None:
        state = make(barriers=frozenset({(1, 1)}))
        assert (1, 1) not in reachable(state, (0, 0), AXES)

    def test_sealed_origin_reaches_nothing(self) -> None:
        """The trapping-capture state: sealed in place, nowhere to go."""
        state = make(thief=(3, 3), barriers=frozenset({(3, 3)}))
        assert reachable(state, (3, 3), AXES) == frozenset()

    def test_off_board_origin_reaches_nothing(self) -> None:
        assert reachable(make(), (9, 9), AXES) == frozenset()

    def test_agent_occupancy_does_not_block(self) -> None:
        assert (3, 3) in reachable(make(cop=(0, 0), thief=(3, 3)), (0, 0), AXES)

    @pytest.mark.parametrize("corner", ORIGIN_CORNERS)
    def test_area_is_convention_independent(self, corner: OriginCorner) -> None:
        """Reachability is geometric; only the direction labels differ."""
        axes = AxisConvention(origin_corner=corner)
        state = make(barriers=frozenset({(1, 1), (2, 2)}))
        assert reachable_area(state, (0, 0), axes) == 47


class TestPartitioning:
    def _split_board(self) -> BoardState:
        """A full wall across row 3 cuts the board into two regions."""
        return make(cop=(0, 0), thief=(6, 6), barriers=frozenset({(3, c) for c in range(7)}))

    def test_a_wall_partitions_the_board(self) -> None:
        state = self._split_board()
        assert reachable_area(state, (0, 0), AXES) == 21
        assert reachable_area(state, (6, 6), AXES) == 21

    def test_regions_are_disjoint(self) -> None:
        state = self._split_board()
        assert not (reachable(state, (0, 0), AXES) & reachable(state, (6, 6), AXES))

    def test_is_connected_across_an_open_board(self) -> None:
        assert is_connected(make(), (0, 0), (6, 6), AXES)

    def test_is_connected_false_across_a_wall(self) -> None:
        assert not is_connected(self._split_board(), (0, 0), (6, 6), AXES)

    def test_one_gap_restores_connection(self) -> None:
        """The self-preservation veto turns on exactly this distinction."""
        state = make(cop=(0, 0), thief=(6, 6), barriers=frozenset({(3, c) for c in range(6)}))
        assert is_connected(state, (0, 0), (6, 6), AXES)


class TestStrategyUseCases:
    def test_sealing_a_corridor_costs_more_than_open_ground(self) -> None:
        """Why area, not distance, scores a barrier."""
        corridor = make(cop=(0, 0), thief=(0, 6), barriers=frozenset({(1, c) for c in range(6)}))
        before = reachable_area(corridor, (0, 6), AXES)
        after = reachable_area(
            make(cop=(0, 0), thief=(0, 6), barriers=corridor.barriers | {(0, 5)}),
            (0, 6),
            AXES,
        )
        assert before - after > 1

    def test_a_cop_can_wall_itself_off_from_the_thief(self) -> None:
        """The placement the self-preservation veto must refuse."""
        state = make(cop=(0, 0), thief=(6, 6), barriers=frozenset({(3, c) for c in range(7)}))
        assert not is_connected(state, state.cop, state.thief, AXES)
