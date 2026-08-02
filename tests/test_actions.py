"""Tests for turn actions and the move-or-place exclusivity rule."""

import dataclasses
import typing

import pytest

from thief_agent.domain.actions import (
    DEFAULT_MAX_BARRIERS,
    Action,
    IllegalActionError,
    MoveAction,
    PlaceBarrier,
    apply_action,
    place_barrier,
)
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.rules import IllegalMoveError, legal_moves

AXES = AxisConvention()


def make(**kw: object) -> BoardState:
    base: dict[str, object] = {"grid_size": 7, "cop": (0, 0), "thief": (3, 3)}
    base.update(kw)
    return BoardState(**base)  # type: ignore[arg-type]


class TestExclusivityByConstruction:
    def test_an_action_is_one_variant_or_the_other(self) -> None:
        """There is no representable value meaning 'move and place'."""
        assert set(typing.get_args(Action)) == {MoveAction, PlaceBarrier}

    def test_moving_never_places_a_barrier(self) -> None:
        after = apply_action(make(), "cop", MoveAction("S"), AXES)
        assert after.barriers == frozenset()
        assert after.barriers_used == 0

    def test_placing_never_moves_the_cop(self) -> None:
        """Forfeiting movement is the cost that makes placement a decision."""
        before = make(cop=(2, 2))
        after = apply_action(before, "cop", PlaceBarrier((2, 3)), AXES)
        assert after.cop == before.cop
        assert after.barriers == frozenset({(2, 3)})

    def test_placing_never_moves_the_thief_either(self) -> None:
        before = make()
        after = apply_action(before, "cop", PlaceBarrier((1, 1)), AXES)
        assert after.thief == before.thief


class TestActionTypes:
    def test_actions_are_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            MoveAction("N").move = "S"  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            PlaceBarrier((1, 1)).at = (2, 2)  # type: ignore[misc]

    def test_actions_are_comparable(self) -> None:
        assert MoveAction("N") == MoveAction("N")
        assert PlaceBarrier((1, 1)) == PlaceBarrier((1, 1))

    def test_variants_are_never_equal(self) -> None:
        # Compared as objects: the two types do not overlap, which mypy
        # rejects as a static comparison but is worth pinning at runtime.
        move: object = MoveAction("N")
        place: object = PlaceBarrier((1, 1))
        assert move != place


class TestOnlyTheCopPlaces:
    def test_thief_cannot_place_a_barrier(self) -> None:
        with pytest.raises(IllegalActionError, match="only the cop"):
            apply_action(make(), "thief", PlaceBarrier((3, 4)), AXES)

    def test_thief_may_still_move(self) -> None:
        assert apply_action(make(), "thief", MoveAction("N"), AXES).thief == (2, 3)


class TestPlaceBarrier:
    def test_returns_a_new_state(self) -> None:
        before = make()
        after = place_barrier(before, (1, 1), AXES)
        assert after is not before
        assert before.barriers == frozenset()

    def test_rejects_an_off_board_cell(self) -> None:
        with pytest.raises(IllegalActionError, match="off a 7 board"):
            place_barrier(make(), (9, 9), AXES)

    def test_adds_to_existing_barriers(self) -> None:
        state = make(barriers=frozenset({(1, 1)}))
        assert place_barrier(state, (2, 2), AXES).barriers == frozenset({(1, 1), (2, 2)})

    def test_preserves_step_and_positions(self) -> None:
        before = make(step=5)
        after = place_barrier(before, (1, 1), AXES)
        assert (after.step, after.cop, after.thief) == (5, before.cop, before.thief)


class TestApplyActionDispatch:
    def test_illegal_move_still_raises_from_the_move_path(self) -> None:
        with pytest.raises(IllegalMoveError):
            apply_action(make(cop=(0, 0)), "cop", MoveAction("N"), AXES)

    def test_honours_the_negotiated_convention(self) -> None:
        flipped = AxisConvention(origin_corner="bottom-left")
        assert apply_action(make(), "thief", MoveAction("N"), flipped).thief == (4, 3)


class TestExhaustiveness:
    def test_dispatch_is_statically_exhaustive(self) -> None:
        """`assert_never` makes mypy fail if a variant is added unhandled."""
        foreign = typing.cast(Action, object())
        with pytest.raises(AssertionError):
            apply_action(make(), "cop", foreign, AXES)


class TestBarrierIsIrreversible:
    def test_barriers_only_ever_grow(self) -> None:
        state = make()
        for cell in ((1, 1), (2, 2), (3, 4)):
            after = place_barrier(state, cell, AXES)
            assert after.barriers >= state.barriers
            state = after
        assert state.barriers == frozenset({(1, 1), (2, 2), (3, 4)})

    def test_no_api_removes_a_barrier(self) -> None:
        """There is deliberately no inverse of place_barrier."""
        import thief_agent.domain.actions as actions

        assert not [n for n in dir(actions) if "remove" in n or "clear" in n]

    def test_replacing_an_existing_barrier_is_refused(self) -> None:
        state = make(barriers=frozenset({(2, 2)}))
        with pytest.raises(IllegalActionError, match="already placed"):
            place_barrier(state, (2, 2), AXES)


class TestBarrierBlocksBothPlayers:
    def test_blocks_the_thief(self) -> None:
        state = make(thief=(3, 3), barriers=frozenset({(2, 3)}))
        assert "N" not in legal_moves(state, "thief", AXES)

    def test_blocks_the_cop_that_placed_it(self) -> None:
        """The cop can imprison itself behind a wall of its own making."""
        state = make(cop=(3, 3), barriers=frozenset({(2, 3)}))
        assert "N" not in legal_moves(state, "cop", AXES)

    def test_a_fully_walled_cop_has_only_stay(self) -> None:
        state = make(cop=(3, 3), barriers=frozenset({(2, 3), (4, 3), (3, 2), (3, 4)}))
        assert legal_moves(state, "cop", AXES) == ["STAY"]


class TestBarrierQuota:
    def test_default_quota_matches_appendix_f(self) -> None:
        assert DEFAULT_MAX_BARRIERS == 14

    def test_placing_up_to_the_quota_is_allowed(self) -> None:
        state = make()
        for i in range(DEFAULT_MAX_BARRIERS):
            state = place_barrier(state, (i // 7, i % 7), AXES)
        assert state.barriers_used == DEFAULT_MAX_BARRIERS

    def test_one_past_the_quota_is_refused(self) -> None:
        state = make()
        for i in range(DEFAULT_MAX_BARRIERS):
            state = place_barrier(state, (i // 7, i % 7), AXES)
        with pytest.raises(IllegalActionError, match="quota exhausted"):
            place_barrier(state, (6, 6), AXES)

    def test_quota_is_raisable_by_agreement(self) -> None:
        """A *minimum* parameter: negotiable upward, never below 14."""
        state = make()
        for i in range(DEFAULT_MAX_BARRIERS):
            state = place_barrier(state, (i // 7, i % 7), AXES, max_barriers=20)
        assert place_barrier(state, (6, 6), AXES, max_barriers=20).barriers_used == 15

    def test_quota_applies_through_apply_action(self) -> None:
        state = make(barriers=frozenset({(0, c) for c in range(7)} | {(1, c) for c in range(7)}))
        assert state.barriers_used == 14
        with pytest.raises(IllegalActionError, match="quota exhausted"):
            apply_action(state, "cop", PlaceBarrier((3, 0)), AXES)
