"""Tests for the core board types."""

import dataclasses

import pytest

from thief_agent.domain.board import DELTAS, MOVES, Barrier, BoardState


def make(**kw: object) -> BoardState:
    base: dict[str, object] = {"grid_size": 7, "cop": (0, 0), "thief": (3, 3)}
    base.update(kw)
    return BoardState(**base)  # type: ignore[arg-type]


class TestMoveSet:
    def test_exactly_five_moves_no_diagonals(self) -> None:
        assert set(MOVES) == {"N", "S", "E", "W", "STAY"}

    def test_every_move_has_a_delta(self) -> None:
        assert set(DELTAS) == set(MOVES)

    def test_north_decreases_row_under_top_left_origin(self) -> None:
        assert DELTAS["N"] == (-1, 0)
        assert DELTAS["S"] == (1, 0)

    def test_stay_does_not_move(self) -> None:
        assert DELTAS["STAY"] == (0, 0)

    def test_no_delta_is_diagonal(self) -> None:
        for move, (drow, dcol) in DELTAS.items():
            assert drow == 0 or dcol == 0, f"{move} is diagonal"


class TestImmutability:
    def test_state_is_frozen(self) -> None:
        state = make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            state.cop = (1, 1)  # type: ignore[misc]

    def test_barrier_record_is_frozen(self) -> None:
        barrier = Barrier(at=(2, 2), placed_at_step=4)
        with pytest.raises(dataclasses.FrozenInstanceError):
            barrier.at = (3, 3)  # type: ignore[misc]

    def test_state_is_hashable_and_comparable(self) -> None:
        assert make() == make()
        assert len({make(), make()}) == 1


class TestValidation:
    @pytest.mark.parametrize("size", [0, -1])
    def test_rejects_non_positive_grid(self, size: int) -> None:
        with pytest.raises(ValueError, match="grid_size"):
            BoardState(grid_size=size, cop=(0, 0), thief=(0, 0))

    def test_rejects_negative_step(self) -> None:
        with pytest.raises(ValueError, match="step"):
            make(step=-1)

    @pytest.mark.parametrize("pos", [(-1, 0), (0, -1), (7, 0), (0, 7)])
    def test_rejects_off_board_agent(self, pos: tuple[int, int]) -> None:
        with pytest.raises(ValueError, match="off a 7 board"):
            make(cop=pos)

    def test_rejects_off_board_barrier(self) -> None:
        with pytest.raises(ValueError, match="barrier"):
            make(barriers=frozenset({(9, 9)}))

    def test_allows_thief_standing_on_a_barrier(self) -> None:
        """The trapping capture places a barrier on the thief's own cell.

        Rejecting this state would make a legitimate win condition
        unrepresentable, so it must remain constructible.
        """
        state = make(thief=(3, 3), barriers=frozenset({(3, 3)}))
        assert state.is_barrier(state.thief)


class TestQueries:
    def test_barriers_used_tracks_the_set(self) -> None:
        assert make().barriers_used == 0
        assert make(barriers=frozenset({(1, 1), (2, 2)})).barriers_used == 2

    @pytest.mark.parametrize("pos", [(0, 0), (6, 6), (3, 3)])
    def test_in_bounds_accepts_board_cells(self, pos: tuple[int, int]) -> None:
        assert make().in_bounds(pos)

    @pytest.mark.parametrize("pos", [(-1, 3), (7, 3), (3, -1), (3, 7)])
    def test_in_bounds_rejects_outside(self, pos: tuple[int, int]) -> None:
        assert not make().in_bounds(pos)

    def test_is_barrier(self) -> None:
        state = make(barriers=frozenset({(2, 2)}))
        assert state.is_barrier((2, 2))
        assert not state.is_barrier((2, 3))

    def test_is_free_requires_on_board_and_unblocked(self) -> None:
        state = make(barriers=frozenset({(2, 2)}))
        assert state.is_free((1, 1))
        assert not state.is_free((2, 2))
        assert not state.is_free((9, 9))

    def test_is_free_ignores_agent_occupancy(self) -> None:
        """Capture is the cop moving onto the thief's cell, so it stays free."""
        assert make().is_free((3, 3))
