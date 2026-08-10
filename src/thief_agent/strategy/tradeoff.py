"""What a barrier costs, measured against what the turn would have bought.

A placement is not free even when the barrier is. The cop does not move on a
turn it places, so every wall is bought with a step of pursuit as well as a
unit of the quota — and the step is the cost that is easy to forget, because
nothing in the board state records the pursuit that did not happen.

So the comparison is made explicitly and both sides are written to the log.
The escape area a placement removes is set against the distance the best
available move would have closed, and the barrier is taken only when it wins.

The two quantities are not the same unit, and pretending otherwise would be
dishonest. Cells of the thief's escape region and cells of Manhattan distance
measure different things, and the exchange rate between them is a judgement,
not a derivation. What makes the comparison defensible is that it is *stated*:
the figures that justified every placement are in the transcript, so a
decision that looks wrong afterwards can be argued with on its own numbers
rather than reconstructed from the board.

On open board this arithmetic almost always refuses. A barrier there removes
one cell while a step closes one cell of distance, and a tie goes to the move
because the move keeps the barrier. That is the intended reading: barriers are
for corridors and corners, and a cop spending them on open ground has already
lost the endgame it has not reached yet.
"""

import logging
from dataclasses import dataclass

from ..domain.actions import DEFAULT_MAX_BARRIERS
from ..domain.axes import AxisConvention
from ..domain.board import BoardState, Move, Position
from ..domain.rules import target_of
from .barriers import BarrierScore, best_placement
from .budget import Budget, looks_like_endgame

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Tradeoff:
    """Both sides of one placement decision, and the verdict."""

    placement: BarrierScore | None
    move_gain: int
    required: int
    budget: Budget
    endgame: bool

    @property
    def placement_value(self) -> int:
        """Escape area the best permitted placement would remove."""
        return self.placement.escape_reduction if self.placement else 0

    @property
    def affordable(self) -> bool:
        """Whether the quota and the reserve allow a barrier at all."""
        return self.budget.may_spend(self.endgame)

    @property
    def place(self) -> bool:
        """Whether to spend the turn on a barrier rather than on pursuit.

        Three conditions, all required. There must be a permitted placement;
        the quota must allow it; and the escape area removed must beat both
        the pursuit forfeited and the bar the budget curve sets for the
        current belief. A tie goes to moving, because moving keeps the
        barrier and a barrier kept can still be spent later.
        """
        if self.placement is None or not self.affordable:
            return False
        return self.placement_value > self.move_gain and self.placement_value >= self.required

    def __str__(self) -> str:
        verdict = "PLACE" if self.place else "MOVE"
        where = self.placement.at if self.placement else None
        return (
            f"{verdict}: placement {where} removes {self.placement_value} "
            f"vs move closing {self.move_gain}; "
            f"bar {self.required}; {self.budget}"
            f"{'; endgame' if self.endgame else ''}"
        )


def distance_closed(state: BoardState, move: Move, target: Position, axes: AxisConvention) -> int:
    """How much nearer ``move`` brings the cop to ``target``.

    Negative when the only legal step is away — which is a real position, and
    one where a barrier looks better than it is. Reporting the loss honestly
    is the point; clamping it to zero would quietly convert a bad turn into a
    neutral one and let a weak placement through on the difference.
    """
    before = manhattan(state.cop, target)
    after = manhattan(target_of(state.cop, move, axes), target)
    return before - after


def manhattan(a: Position, b: Position) -> int:
    """Steps between two cells, ignoring barriers."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def weigh(
    state: BoardState,
    axes: AxisConvention,
    target: Position,
    best_move: Move | None,
    concentration: float = 1.0,
    max_barriers: int = DEFAULT_MAX_BARRIERS,
) -> Tradeoff:
    """Compare the best placement against the best move, and log both sides.

    ``max_barriers`` is threaded from the brain rather than defaulted here at
    the point of use. The quota is a *minimum* in Appendix F — raisable by
    agreement, and therefore genuinely variable between matches — so a policy
    that plans against the book value while the guard enforces the negotiated
    one does not merely play badly. It proposes a placement the guard then
    refuses, which is a crash on the cop's own turn rather than a decision.
    """
    budget = Budget(used=state.barriers_used, limit=max_barriers)
    endgame = looks_like_endgame(state, axes, target)
    call = Tradeoff(
        placement=best_placement(state, axes, target),
        move_gain=distance_closed(state, best_move, target, axes) if best_move else 0,
        required=budget.required_value(concentration),
        budget=budget,
        endgame=endgame,
    )
    logger.info("step %d %s", state.step, call)
    return call
