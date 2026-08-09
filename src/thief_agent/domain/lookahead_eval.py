"""What a searched board is worth, in the thief's favour.

One function serves both roles because the game is zero-sum: the search
negates as it alternates, so the cop reads the same number with the opposite
sign. Writing two evaluators would be two chances to disagree about what a
position means, and a search whose two halves disagree plays worse than one
that is merely simple.

**Room is the leading term, not distance.** Appendix F pays the thief 10 for
surviving the step threshold and 5 when the cop takes it late, so the thief is
playing for time rather than for separation. Distance buys time only while
there is somewhere to spend it: a thief three cells away in a dead-end corridor
is caught, and a thief adjacent to the cop on open board usually is not. So
reachable area leads, degree of the occupied cell follows, and distance breaks
what is left. This is the same judgement the shipped brain encodes as a veto,
priced continuously so a search can trade against it instead of obeying it.

The weights are *negotiable* tuning, not Appendix F values, and they were
settled by playing the results rather than by argument.
"""

from .axes import AxisConvention
from .board import Agent, BoardState
from .rules import legal_moves
from .search import reachable_area

__all__ = ["AREA", "DEGREE", "DISTANCE", "ROOM", "evaluate"]

AREA = 3.0
"""Weight on free cells the thief can still reach. The dominant term: it is
what makes sealing a region worth more to the cop than closing distance, and
what stops the thief entering a pocket it cannot leave."""

DEGREE = 2.0
"""Weight on exits from the thief's own cell. Cheap insurance against the
one-move trap that reachable area alone reads as survivable."""

DISTANCE = 1.0
"""Weight on separation. Real but least: distance without room is a countdown."""

MOBILITY = 1.5
"""Weight on the cop's own exits, counted *against* the thief.

The cop builds the walls, so it is the only side that can wall itself in — and
a cop with no legal move is not a bad position but an aborted match, scoring
zero for both teams. :func:`~.lookahead_moves.candidates` makes that
unreachable outright; this makes the approach to it visibly expensive, so the
search keeps its own room rather than merely avoiding the last step into a
cell it cannot leave.
"""

ROOM = 6
"""Free cells below which a region counts as a trap rather than an escape."""


def evaluate(state: BoardState, axes: AxisConvention, turn: Agent) -> float:
    """The board's value to ``turn``, positive when it is winning.

    Signed for the side to move so the negamax above can stay sign-agnostic.
    """
    score = _for_thief(state, axes)
    return score if turn == "thief" else -score


def _for_thief(state: BoardState, axes: AxisConvention) -> float:
    """The board's value to the thief, on a scale the search can compare.

    Every term is a count, so the units are cells and the weights are simply
    how many cells of one thing another is worth.
    """
    room = reachable_area(state, state.thief, axes)
    exits = len(legal_moves(state, "thief", axes))
    apart = abs(state.thief[0] - state.cop[0]) + abs(state.thief[1] - state.cop[1])
    hunter = len(legal_moves(state, "cop", axes))
    return AREA * room + DEGREE * exits + DISTANCE * apart - MOBILITY * hunter
