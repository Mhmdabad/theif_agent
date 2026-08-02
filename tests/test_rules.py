"""Tests for movement legality."""

import pytest

from thief_agent.domain.axes import ORIGIN_CORNERS, AxisConvention, OriginCorner
from thief_agent.domain.board import MOVES, Agent, BoardState, Move
from thief_agent.domain.rules import (
    blocked_neighbours,
    is_legal_move,
    legal_moves,
    position_of,
    target_of,
)

AXES = AxisConvention()


def make(**kw: object) -> BoardState:
    base: dict[str, object] = {"grid_size": 7, "cop": (0, 0), "thief": (3, 3)}
    base.update(kw)
    return BoardState(**base)  # type: ignore[arg-type]


class TestPositionOf:
    @pytest.mark.parametrize(("agent", "expected"), [("cop", (0, 0)), ("thief", (3, 3))])
    def test_reads_the_right_agent(self, agent: Agent, expected: tuple[int, int]) -> None:
        assert position_of(make(), agent) == expected


class TestTargetOf:
    def test_applies_the_delta(self) -> None:
        assert target_of((3, 3), "N", AXES) == (2, 3)
        assert target_of((3, 3), "S", AXES) == (4, 3)
        assert target_of((3, 3), "E", AXES) == (3, 4)
        assert target_of((3, 3), "W", AXES) == (3, 2)

    def test_stay_is_a_fixed_point(self) -> None:
        assert target_of((3, 3), "STAY", AXES) == (3, 3)

    def test_may_return_an_off_board_cell(self) -> None:
        """Legality is a separate question; this only computes the target."""
        assert target_of((0, 0), "N", AXES) == (-1, 0)

    def test_respects_the_negotiated_convention(self) -> None:
        flipped = AxisConvention(origin_corner="bottom-left")
        assert target_of((3, 3), "N", AXES) == (2, 3)
        assert target_of((3, 3), "N", flipped) == (4, 3)


class TestLegalMoves:
    def test_open_board_allows_everything(self) -> None:
        assert legal_moves(make(), "thief", AXES) == list(MOVES)

    def test_never_returns_a_move_off_the_board(self) -> None:
        moves = legal_moves(make(cop=(0, 0)), "cop", AXES)
        assert "N" not in moves
        assert "W" not in moves
        assert set(moves) == {"S", "E", "STAY"}

    def test_barriers_block_movement(self) -> None:
        state = make(thief=(3, 3), barriers=frozenset({(2, 3), (4, 3)}))
        assert set(legal_moves(state, "thief", AXES)) == {"E", "W", "STAY"}

    def test_order_is_stable(self) -> None:
        """Replay determinism depends on both peers iterating identically."""
        state = make(barriers=frozenset({(2, 3)}))
        assert legal_moves(state, "thief", AXES) == legal_moves(state, "thief", AXES)
        assert legal_moves(state, "thief", AXES) == [m for m in MOVES if m != "N"]

    def test_agent_occupancy_does_not_block(self) -> None:
        """The cop moving onto the thief's cell is how a capture happens."""
        state = make(cop=(3, 2), thief=(3, 3))
        assert "E" in legal_moves(state, "cop", AXES)

    @pytest.mark.parametrize("corner", ORIGIN_CORNERS)
    def test_corner_cell_always_loses_exactly_two_moves(self, corner: OriginCorner) -> None:
        axes = AxisConvention(origin_corner=corner)
        assert len(legal_moves(make(cop=(0, 0)), "cop", axes)) == 3

    @pytest.mark.parametrize("move", [m for m in MOVES if m != "STAY"])
    def test_no_diagonals_exist_to_be_played(self, move: Move) -> None:
        drow, dcol = AXES.deltas[move]
        assert drow == 0 or dcol == 0


class TestStayAndEnclosure:
    def test_stay_survives_full_encirclement(self) -> None:
        """Standing still stays legal, so enclosure is judged on neighbours."""
        state = make(thief=(3, 3), barriers=frozenset({(2, 3), (4, 3), (3, 2), (3, 4)}))
        assert legal_moves(state, "thief", AXES) == ["STAY"]

    def test_stay_is_illegal_when_standing_on_a_barrier(self) -> None:
        """The trapping-capture state: the thief's own cell became blocked."""
        state = make(thief=(3, 3), barriers=frozenset({(3, 3)}))
        assert "STAY" not in legal_moves(state, "thief", AXES)

    def test_encircled_thief_has_four_blocked_neighbours(self) -> None:
        state = make(thief=(3, 3), barriers=frozenset({(2, 3), (4, 3), (3, 2), (3, 4)}))
        assert blocked_neighbours(state, state.thief, AXES) == 4

    def test_board_edge_counts_as_blocked(self) -> None:
        assert blocked_neighbours(make(), (0, 0), AXES) == 2

    def test_corner_plus_two_barriers_is_encirclement(self) -> None:
        state = make(cop=(6, 6), thief=(0, 0), barriers=frozenset({(1, 0), (0, 1)}))
        assert blocked_neighbours(state, (0, 0), AXES) == 4

    def test_open_cell_has_no_blocked_neighbours(self) -> None:
        assert blocked_neighbours(make(), (3, 3), AXES) == 0


class TestIsLegalMove:
    def test_agrees_with_legal_moves(self) -> None:
        state = make(cop=(0, 0), barriers=frozenset({(1, 0)}))
        for move in MOVES:
            assert is_legal_move(state, "cop", move, AXES) == (
                move in legal_moves(state, "cop", AXES)
            )
