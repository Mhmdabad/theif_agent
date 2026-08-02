"""Stage 1 acceptance suite: the gate, exercised end to end.

The per-module tests check units in isolation. This file checks the gate the
rulebook actually states — that a full race runs to termination with the rules
enforced — by playing complete sub-games rather than asserting on predicates.

Anything that passes here but fails in a real match is a gap in the model, not
in the code, which is why these read as scenarios rather than unit tests.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from thief_agent.domain.actions import (
    DEFAULT_MAX_BARRIERS,
    IllegalActionError,
    MoveAction,
    PlaceBarrier,
    apply_action,
)
from thief_agent.domain.axes import ORIGIN_CORNERS, AxisConvention, OriginCorner
from thief_agent.domain.board import MOVES, BoardState
from thief_agent.domain.outcome import DEFAULT_SURVIVAL_THRESHOLD
from thief_agent.domain.rules import IllegalMoveError, advance_turn, legal_moves
from thief_agent.domain.scoring import Outcome, evaluate, scores_for
from thief_agent.shared.config import validate

AXES = AxisConvention()


def shipped() -> dict[str, Any]:
    return json.loads((Path(__file__).parents[1] / "config/game.json").read_text())  # type: ignore[no-any-return]


def start(**kw: object) -> BoardState:
    cfg = shipped()["board_and_agents"]
    base: dict[str, object] = {
        "grid_size": cfg["grid_size"],
        "cop": tuple(cfg["cop_start"]),
        "thief": tuple(cfg["thief_start"]),
    }
    base.update(kw)
    return BoardState(**base)  # type: ignore[arg-type]


class TestFullRaceTerminates:
    def test_thief_survives_a_full_race_untouched(self) -> None:
        """Both stand still for the whole clock: survival, 5/10."""
        state = start()
        for _ in range(DEFAULT_SURVIVAL_THRESHOLD):
            state = apply_action(state, "cop", MoveAction("STAY"), AXES)
            state = apply_action(state, "thief", MoveAction("STAY"), AXES)
            state = advance_turn(state)
        assert evaluate(state, AXES) is Outcome.SURVIVAL
        assert scores_for(Outcome.SURVIVAL) == (5, 10)

    def test_cop_walks_to_the_thief_and_captures(self) -> None:
        """A real pursuit down a row and a column ends in 20/5."""
        state = start()
        while state.cop[0] < state.thief[0]:
            state = apply_action(state, "cop", MoveAction("S"), AXES)
        while state.cop[1] < state.thief[1]:
            state = apply_action(state, "cop", MoveAction("E"), AXES)
        assert evaluate(state, AXES) is Outcome.CAPTURE
        assert scores_for(Outcome.CAPTURE) == (20, 5)

    def test_race_never_exceeds_the_move_ceiling(self) -> None:
        max_moves = shipped()["movement_and_barriers"]["max_moves"]
        state = start()
        for _ in range(max_moves):
            state = advance_turn(state)
        assert state.step == max_moves


class TestCaptureVariants:
    def test_overlap(self) -> None:
        assert evaluate(start(cop=(3, 3), thief=(3, 3)), AXES) is Outcome.CAPTURE

    def test_trapping_placement_wins(self) -> None:
        """Cop steps adjacent, then seals the thief's own cell."""
        state = start(cop=(3, 2), thief=(3, 3))
        state = apply_action(state, "cop", PlaceBarrier((3, 3)), AXES)
        assert evaluate(state, AXES) is Outcome.CAPTURE

    def test_enclosure_in_a_corner_costs_two_barriers(self) -> None:
        state = start(cop=(1, 1), thief=(0, 0))
        state = apply_action(state, "cop", PlaceBarrier((0, 1)), AXES)
        state = apply_action(state, "cop", PlaceBarrier((1, 0)), AXES)
        assert state.barriers_used == 2
        assert evaluate(state, AXES) is Outcome.CAPTURE


class TestRulesAreEnforced:
    def test_no_diagonal_exists_to_be_played(self) -> None:
        assert set(MOVES) == {"N", "S", "E", "W", "STAY"}

    def test_off_board_move_is_refused(self) -> None:
        with pytest.raises(IllegalMoveError):
            apply_action(start(cop=(0, 0)), "cop", MoveAction("N"), AXES)

    def test_move_into_a_barrier_is_refused(self) -> None:
        state = start(thief=(3, 3), barriers=frozenset({(2, 3)}))
        with pytest.raises(IllegalMoveError):
            apply_action(state, "thief", MoveAction("N"), AXES)

    def test_thief_cannot_place_a_barrier(self) -> None:
        with pytest.raises(IllegalActionError, match="only the cop"):
            apply_action(start(), "thief", PlaceBarrier((3, 4)), AXES)

    def test_the_last_barrier_is_allowed_and_the_next_refused(self) -> None:
        """Quota boundary, exercised through the real action path.

        A one-step reach means a cop cannot spend fourteen barriers along any
        straight walk, so the first thirteen are given as start state and only
        the boundary is played. That limitation is itself the point: a
        containment chain is a multi-turn commitment, not something a
        stationary cop can lay down.
        """
        spent = frozenset({(0, c) for c in range(7)} | {(2, c) for c in range(6)})
        assert len(spent) == DEFAULT_MAX_BARRIERS - 1
        state = start(cop=(1, 5), thief=(6, 6), barriers=spent)

        state = apply_action(state, "cop", PlaceBarrier((2, 6)), AXES)
        assert state.barriers_used == DEFAULT_MAX_BARRIERS

        with pytest.raises(IllegalActionError, match="quota exhausted"):
            apply_action(state, "cop", PlaceBarrier((1, 6)), AXES)

    def test_legal_moves_never_offers_an_inapplicable_move(self) -> None:
        """Every move offered must actually apply, from many positions."""
        for row in range(7):
            for col in range(7):
                state = start(thief=(row, col), barriers=frozenset({(3, 3), (4, 4)}))
                if state.is_barrier(state.thief):
                    continue
                for move in legal_moves(state, "thief", AXES):
                    apply_action(state, "thief", MoveAction(move), AXES)


class TestConfigDrivenNotHardCoded:
    def test_shipped_config_validates(self) -> None:
        validate(shipped())

    def test_start_positions_come_from_config(self) -> None:
        cfg = shipped()["board_and_agents"]
        assert start().thief == tuple(cfg["thief_start"])
        assert start().cop == tuple(cfg["cop_start"])

    @pytest.mark.parametrize("corner", ORIGIN_CORNERS)
    def test_a_race_terminates_under_every_convention(self, corner: OriginCorner) -> None:
        axes = AxisConvention(origin_corner=corner)
        state = start()
        for _ in range(DEFAULT_SURVIVAL_THRESHOLD):
            state = apply_action(state, "thief", MoveAction("STAY"), axes)
            state = advance_turn(state)
        assert evaluate(state, axes) is Outcome.SURVIVAL
