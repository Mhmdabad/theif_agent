"""Stage 3 acceptance tests (#43).

Three things the issue asks for, gathered here rather than scattered through
the suites that produced them, so the stage's criteria can be read in one
place: the policy never returns an illegal move over random boards; the
dead-end tie-break rejects further-but-trapped; and the decision is
deterministic.

The determinism criterion is covered in depth in ``test_determinism.py`` —
across processes under four hash seeds, across a whole match, and with the
RNG stream asserted untouched. What is here is the criterion stated plainly,
so #43 is answered without duplicating that file.
"""

import random

import pytest

from thief_agent.domain.actions import MoveAction
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.rules import legal_moves, target_of
from thief_agent.domain.search import reachable
from thief_agent.strategy.base import NoLegalActionError
from thief_agent.strategy.thief_brain import ThiefBrain, open_neighbours

AXES = AxisConvention()

CORRIDOR = frozenset({(0, 3), (0, 4), (0, 5), (0, 6), (2, 3), (2, 4), (2, 5), (2, 6)})
"""Row 1, columns 3-6 walled above and below: a four-cell dead-end corridor."""


def make(**kw: object) -> BoardState:
    cop = kw.get("cop", (0, 0))
    thief = kw.get("thief", (3, 3))
    barriers = kw.get("barriers", frozenset())
    assert isinstance(cop, tuple) and isinstance(thief, tuple)
    assert isinstance(barriers, frozenset | set)
    return BoardState(cop=cop, thief=thief, grid_size=7, barriers=frozenset(barriers))


class TestNeverIllegal:
    """#43, first criterion: over randomly generated boards."""

    def test_the_policy_output_is_always_legal(self) -> None:
        """The guard's property test (#40) forces moves into it. This one asks
        the *policy* — the guard is the backstop, not the thing under test."""
        rng = random.Random(43)
        cells = [(row, col) for row in range(7) for col in range(7)]
        decided = 0
        for _ in range(400):
            walls = frozenset(rng.sample(cells, rng.randint(0, 24)))
            free = [cell for cell in cells if cell not in walls]
            if len(free) < 2:
                continue
            state = make(cop=rng.choice(free), thief=rng.choice(free), barriers=walls)
            legal = legal_moves(state, "thief", AXES)
            if not legal:
                with pytest.raises(NoLegalActionError):
                    ThiefBrain(axes=AXES).decide(state)
                continue
            action = ThiefBrain(axes=AXES).decide(state).action
            assert isinstance(action, MoveAction)
            assert action.move in legal
            assert state.is_free(target_of(state.thief, action.move, AXES))
            decided += 1
        assert decided > 300, f"only {decided} boards produced a decision"

    def test_a_thief_with_no_legal_move_raises_rather_than_inventing_one(self) -> None:
        walls = frozenset({(2, 3), (4, 3), (3, 2), (3, 4), (3, 3)})
        with pytest.raises(NoLegalActionError, match="no legal move"):
            ThiefBrain(axes=AXES).decide(make(thief=(3, 3), barriers=walls))


class TestDeadEndRegression:
    """#43, second criterion: further-but-trapped is rejected."""

    def test_the_corridor_really_is_a_trap(self) -> None:
        """Establish the board before asserting anything about the policy."""
        state = make(cop=(1, 0), thief=(1, 2), barriers=CORRIDOR)
        assert open_neighbours(state, (1, 3), AXES) == 2
        assert open_neighbours(state, (1, 6), AXES) == 1
        sealed = make(cop=(1, 0), thief=(1, 3), barriers=CORRIDOR | {(1, 2)})
        assert reachable(sealed, (1, 3), AXES) == frozenset({(1, 3), (1, 4), (1, 5), (1, 6)})

    def test_it_refuses_the_corridor_though_the_corridor_is_further(self) -> None:
        """The regression the issue names.

        From (1, 2) with the cop at (1, 0), three moves all reach distance 3:
        N to (0, 2), E into the corridor mouth, and S to (2, 2). All three
        strictly increase distance, so the corner-aversion *veto* exempts every
        one of them — distance alone cannot tell them apart, and neither can
        escape area, since all three share the thief's component.

        Degree can. (2, 2) has three open sides, the corridor mouth has two,
        and the thief goes south.
        """
        state = make(cop=(1, 0), thief=(1, 2), barriers=CORRIDOR)
        brain = ThiefBrain(axes=AXES)
        assert not brain.is_cramped(state, "E", state.cop)
        assert brain._rank(state, "E", state.cop)[1] == brain._rank(state, "S", state.cop)[1]
        action = brain.decide(state).action
        assert isinstance(action, MoveAction)
        assert action.move == "S"

    def test_and_still_refuses_it_when_the_open_option_is_gone(self) -> None:
        """Sealing (2, 2) removes the good answer. The corridor is still not
        taken — (0, 2) is an edge run rather than a four-cell dead end."""
        walls = CORRIDOR | {(2, 2)}
        state = make(cop=(1, 0), thief=(1, 2), barriers=walls)
        action = ThiefBrain(axes=AXES).decide(state, threat=state.cop).action
        assert isinstance(action, MoveAction)
        assert action.move != "E"

    def test_the_tie_break_is_degree_not_move_order(self) -> None:
        """Without this, the test above passes for the wrong reason: N happens
        to precede E in MOVES, so a policy ignoring degree would also avoid the
        corridor here."""
        state = make(cop=(1, 0), thief=(1, 2), barriers=CORRIDOR)
        brain = ThiefBrain(axes=AXES)
        south, east = brain._rank(state, "S", state.cop), brain._rank(state, "E", state.cop)
        assert south[1] == east[1]
        assert south[2] > east[2]
        assert south > east

    def test_how_deep_the_check_goes(self) -> None:
        """An honest limit, recorded rather than glossed.

        Degree is local: it counts one cell's open sides and nothing beyond.
        With (2, 2) sealed, (0, 2) and the corridor mouth both have degree 2,
        so the ranking cannot separate a two-cell edge run from a four-cell
        dead end and falls through to MOVES order. Distinguishing them needs
        lookahead this policy deliberately does not have — but note the
        failure is bounded: both candidates are already cramped, so the
        position was bad before the choice was made.
        """
        walls = CORRIDOR | {(2, 2)}
        state = make(cop=(1, 0), thief=(1, 2), barriers=walls)
        brain = ThiefBrain(axes=AXES)
        assert brain._rank(state, "N", state.cop)[:3] == brain._rank(state, "E", state.cop)[:3]


class TestDeterminismCriterion:
    """#43, third criterion. Depth lives in test_determinism.py."""

    def test_same_state_and_config_yields_the_same_action(self) -> None:
        state = make(cop=(2, 2), thief=(5, 5))
        assert (
            ThiefBrain(axes=AXES, seed=7).decide(state).action
            == ThiefBrain(axes=AXES, seed=7).decide(state).action
        )

    def test_it_holds_on_the_regression_board_too(self) -> None:
        state = make(cop=(1, 0), thief=(1, 2), barriers=CORRIDOR)
        assert (
            ThiefBrain(axes=AXES, seed=1).decide(state).action
            == ThiefBrain(axes=AXES, seed=2).decide(state).action
        )
