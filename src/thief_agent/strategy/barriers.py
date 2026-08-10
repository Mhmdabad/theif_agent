"""Deciding which cell is worth a barrier.

Fourteen barriers, thirty-five turns. A placement also forfeits the cop's
movement for that turn, so every wall costs a step of pursuit as well as a
unit of a scarce resource — which makes "is this cell worth sealing" a question
with a real answer rather than a preference.

Three axes, in the order they matter:

**Escape-area reduction.** How many cells the thief can still reach after the
seal, compared with before. This is the only axis that measures the actual
objective. A barrier on open ground shaves off nothing and the flood fill says
so; one that closes a corridor takes a whole region.

Once a belief map exists the reduction is **weighted by the probability the
thief is in the region being cut off**. Area alone counts cells; what the cop
is buying is the chance the thief is standing in them. Sealing a large empty
region spends one of fourteen barriers and a full turn of pursuit to remove
somewhere the thief demonstrably is not — and on a board with a live belief
map, the largest regions are frequently the emptiest, because that is where
the evidence has already ruled the thief out.

**Chain progress.** A wall only encloses when it *lands on something* — an
existing barrier, or the board edge. Appendix D's arithmetic follows from this:
enclosure costs two barriers in a corner, three on an edge, four in the open,
because the corner supplies two sides for free. A cell whose neighbours are
already sealed or off-board is a cell where the next barrier finishes work
already paid for.

**Self-cost.** The rules do not stop the cop walling *itself* off, and a
greedy sequence of locally excellent barriers will do exactly that.

That last axis is a **hard constraint**, not a weight. Two placements are
refused outright however well they score: one that cuts the cop off from the
region it is hunting, and one that leaves the cop with no legal move at all.
The second is the more expensive mistake. A cop that cannot move cannot answer
its turn, and an unanswered turn is a technical loss — which scores **zero for
both sides**, converting a game we were winning into a game nobody played.

Refused candidates are still scored and still logged. Dropping them silently
would leave a match transcript showing a barrier that went somewhere odd with
no record of what was rejected or why.

**One placement can end the match**, and that case is checked before any of
the above. A barrier on the thief's own cell is a trapping capture; a barrier
closing its last open side is an enclosure capture. Both are worth twenty
points outright, and both are easy to walk straight past while minimising
distance — the winning cell frequently scores *worse* on escape reduction than
its neighbours, because there is barely any escape left to reduce.
"""

import logging

from ..domain.axes import AxisConvention
from ..domain.belief import Belief
from ..domain.board import BoardState, Position
from .barriers_geometry import chain_progress, severed_mass, still_reaches
from .barriers_score import SELF_PENALTY, BarrierScore, score_placement
from .barriers_win import candidates, winning_placement, wins_outright

__all__ = [
    "SELF_PENALTY",
    "BarrierScore",
    "best_placement",
    "candidates",
    "chain_progress",
    "rank_placements",
    "safe_placements",
    "score_placement",
    "severed_mass",
    "still_reaches",
    "winning_placement",
    "wins_outright",
]

logger = logging.getLogger(__name__)


def rank_placements(
    state: BoardState, axes: AxisConvention, target: Position, belief: Belief | None = None
) -> list[BarrierScore]:
    """Every legal placement this turn, best first.

    Ties resolve by row then column, so two peers replaying the same match rank
    them identically. A ranking that depended on set iteration order would be
    reproducible on one machine and nowhere else.
    """
    scored = [
        score_placement(state, cell, axes, target, belief) for cell in candidates(state, axes)
    ]
    scored.sort(key=lambda score: (-score.total, score.at))
    if scored:
        logger.info(
            "barrier candidates from cop=%s target=%s: %s",
            state.cop,
            target,
            "; ".join(str(score) for score in scored),
        )
    else:
        logger.info("no barrier candidates from cop=%s: every cell in reach is sealed", state.cop)
    return scored


def safe_placements(
    state: BoardState, axes: AxisConvention, target: Position, belief: Belief | None = None
) -> list[BarrierScore]:
    """Ranked placements with the refused ones removed.

    The filter is separate from the ranking so that both survive: callers get
    only permitted placements, and the log still records what was rejected.
    """
    permitted = [score for score in rank_placements(state, axes, target, belief) if score.permitted]
    if not permitted:
        logger.info("no permitted placement from cop=%s: every candidate is refused", state.cop)
    return permitted


def best_placement(
    state: BoardState, axes: AxisConvention, target: Position, belief: Belief | None = None
) -> BarrierScore | None:
    """The best placement the constraint allows, or ``None`` if there is none.

    ``None`` means *do not place a barrier this turn*, never "place the least
    bad one". Not placing costs a barrier we keep; placing a refused one can
    cost the match.
    """
    permitted = safe_placements(state, axes, target, belief)
    return permitted[0] if permitted else None
