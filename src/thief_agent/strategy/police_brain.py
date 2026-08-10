"""The cop's decision-making.

Pursue the target by Manhattan distance, breaking ties by **containment
value** rather than by position.

Distance alone decides where to step but not which of several equally close
steps is worth taking, and those are not equivalent. The rulebook's real
objective for this agent is not *chase the thief* but *shrink the space the
thief has*: enclosure costs two barriers in a corner, three on an edge and
four in open board, so herding matters more than closing.

The tie-break scores a candidate by how much it reduces the thief's reachable
area, falling back to proximity to the board edge when reachability cannot
separate them. Both are cheap and both point the pursuit the same way.

The cop has a second kind of turn. :meth:`PoliceBrain._decide_move` chooses
between relocating and forfeiting movement to place a barrier, in a fixed
order that reflects what each check costs to get wrong:

1. a placement that **wins outright** this turn, taken before anything else
   is consulted, because neither escape area nor our own mobility means
   anything once the match is over;
2. otherwise the best move and the best permitted placement are weighed
   against each other, with both sides of the comparison written to the log.
"""

import logging
from dataclasses import dataclass, replace

from ..domain.actions import Action, MoveAction, PlaceBarrier
from ..domain.board import Agent, BoardState
from .barriers import winning_placement
from .police_brain_pursuit import PursuitRanking, manhattan
from .tradeoff import weigh

__all__ = ["PoliceBrain", "manhattan"]

logger = logging.getLogger(__name__)


@dataclass
class PoliceBrain(PursuitRanking):
    """Pursues the highest-belief cell by minimising Manhattan distance."""

    @property
    def role(self) -> Agent:
        return "cop"

    def _decide_move(self, state: BoardState, **context: object) -> Action:
        """Relocate, or forfeit the turn to place a barrier.

        The win check runs first and unconditionally. It deliberately bypasses
        the value scorer and the self-preservation gate, both of which refuse
        the winning placement for defensible reasons that stop applying the
        moment the match ends.

        Everything else is a comparison, and the comparison is logged. A
        barrier costs a step of pursuit that nothing in the board state
        records, so a placement that is never weighed against the move it
        replaced is a placement nobody can argue with afterwards.

        The seed goes out on every turn rather than once at startup. A match
        transcript is the artefact a bug report is reconstructed from, and a
        seed recorded only in a line that may have been truncated, rotated or
        never captured is a seed the reproduction does not have.

        The move is validated *before* it is weighed, not only afterwards by
        the guard in :meth:`~.base.BrainBase.decide`. An illegal move has no
        meaningful distance: stepping off the board produces a number, the
        comparison consumes it, and a placement gets chosen on the strength of
        arithmetic about a cell that does not exist. Worse, choosing to place
        would mean the illegal move never reaches the guard at all, so a
        broken policy would be silently absorbed rather than reported.
        """
        goal = self.target(state, **context)
        state = replace(state, thief=goal)
        logger.info("step %d seed=%d cop=%s target=%s", state.step, self.seed, state.cop, goal)
        win = winning_placement(state, self.axes, self.max_barriers)
        if win is not None:
            return PlaceBarrier(win)

        move = self._pick_move(state, **context)
        self._guard(state, MoveAction(move))
        call = weigh(state, self.axes, goal, move, self.concentration(**context), self.max_barriers)
        if call.place and call.placement is not None:
            return PlaceBarrier(call.placement.at)
        return MoveAction(move)

    def concentration(self, **context: object) -> float:
        """How sharply belief is focused, in ``[0, 1]``.

        Runtime supplies the real figure. A direct caller that omits it gets
        zero, matching the deterministic uninformative prior used by
        :meth:`target` rather than inventing certainty.
        """
        supplied = context.get("concentration")
        return float(supplied) if isinstance(supplied, int | float) else 0.0
