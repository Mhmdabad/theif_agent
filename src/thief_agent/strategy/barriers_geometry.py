"""The board questions a barrier score is assembled from.

Split out of :mod:`.barriers` so that module keeps to the file-length budget.
Each function here answers one thing about a cell or about the state a seal
would produce — which sides are already closed, whether the cop can still get
where it is going, and how much belief the seal takes away. None of them
decides anything; :mod:`.barriers_score` combines them into a record and
:mod:`.barriers` ranks the records and re-exports every name here.
"""

from ..domain.axes import AxisConvention
from ..domain.belief import Belief
from ..domain.board import MOVES, BoardState, Position
from ..domain.rules import target_of
from ..domain.search import is_connected, reachable


def chain_progress(state: BoardState, at: Position, axes: AxisConvention) -> int:
    """How many of ``at``'s four sides are already closed.

    Counts sealed neighbours and off-board sides alike, because they close a
    line equally well — that equivalence is what makes a corner cheaper to
    enclose than open ground, and it is the whole reason to herd toward edges.
    """
    closed = 0
    for move in MOVES:
        if move == "STAY":
            continue
        neighbour = target_of(at, move, axes)
        if not state.in_bounds(neighbour) or state.is_barrier(neighbour):
            closed += 1
    return closed


def still_reaches(sealed: BoardState, target: Position, axes: AxisConvention) -> bool:
    """Whether the cop can still get to ``target`` in this post-seal state.

    Not simply :func:`is_connected` from the cop's cell, because the cop may
    seal the cell it is standing on. A sealed origin has no reachable set, but
    the cop is not trapped by it: leaving asks whether the *destination* is
    free, so all four steps remain legal and only re-entry is lost. Reading
    that as "cut off" would put a permanent 1000-point penalty on a placement
    that is often the best wall available.
    """
    if sealed.is_free(sealed.cop):
        return is_connected(sealed, sealed.cop, target, axes)
    exits = (target_of(sealed.cop, move, axes) for move in MOVES if move != "STAY")
    return any(
        sealed.is_free(exit_cell) and is_connected(sealed, exit_cell, target, axes)
        for exit_cell in exits
    )


def severed_mass(
    state: BoardState,
    sealed: BoardState,
    at: Position,
    axes: AxisConvention,
    target: Position,
    belief: Belief,
) -> float:
    """Belief carried by the cells the seal removes from the thief's reach.

    The cells lost are those reachable before and not after, plus the sealed
    cell itself — a barrier on the thief's own most-likely square removes that
    square's mass even though it was never "cut off" from anything. Summing
    belief over exactly those cells answers what the wall is actually buying.
    """
    lost = reachable(state, target, axes) - reachable(sealed, target, axes)
    return sum(belief.at(cell) for cell in lost | {at})
