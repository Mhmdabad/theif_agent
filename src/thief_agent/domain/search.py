"""Reachability over the open board.

Breadth-first flood fill across free cells. The strategy layer needs this for
two distinct jobs, and both are load-bearing for the cop:

**Scoring a candidate barrier.** The value of sealing a cell is how much it
shrinks the thief's reachable area, weighted by the belief mass in the region
being cut off. Raw distance is a poor proxy — a barrier that closes a corridor
is worth far more than one that shaves a cell off open ground.

**The self-preservation veto.** A placement that disconnects the cop from the
region it is hunting is worse than no placement at all: the rules permit the
cop to wall itself in, and a greedy barrier can imprison it behind a wall of
its own making. :func:`is_connected` is the check that refuses those.
"""

from collections import deque

from .axes import AxisConvention
from .board import MOVES, BoardState, Position
from .rules import target_of


def reachable(state: BoardState, origin: Position, axes: AxisConvention) -> frozenset[Position]:
    """Every free cell reachable from ``origin`` by orthogonal steps.

    Includes ``origin`` itself when it is free. A sealed origin yields the
    empty set: a piece sealed in place has nowhere to go, which is exactly the
    trapping-capture state.

    Agent occupancy does not block, matching movement legality — cells are open
    or sealed, and an opponent standing on one does not close it.
    """
    if not state.is_free(origin):
        return frozenset()
    seen = {origin}
    queue = deque([origin])
    while queue:
        cell = queue.popleft()
        for move in MOVES:
            if move == "STAY":
                continue
            neighbour = target_of(cell, move, axes)
            if neighbour not in seen and state.is_free(neighbour):
                seen.add(neighbour)
                queue.append(neighbour)
    return frozenset(seen)


def reachable_area(state: BoardState, origin: Position, axes: AxisConvention) -> int:
    """How many free cells ``origin`` can still reach."""
    return len(reachable(state, origin, axes))


def is_connected(
    state: BoardState, origin: Position, target: Position, axes: AxisConvention
) -> bool:
    """Whether ``target`` is reachable from ``origin`` across free cells."""
    return target in reachable(state, origin, axes)
