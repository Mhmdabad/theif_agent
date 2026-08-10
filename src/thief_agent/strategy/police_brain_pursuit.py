"""Where to step, and which of several equally close steps is worth taking.

Split out of :mod:`.police_brain` so that module keeps to the file-length
budget. This half is the pursuit half: the cell to chase, the legal move that
gets closest to it, and the containment tie-break that separates candidates
distance alone cannot. :class:`~.police_brain.PoliceBrain` subclasses
:class:`PursuitRanking` and adds the barrier turn on top; :mod:`.police_brain`
re-exports :func:`manhattan`.

Kept as a base class rather than loose functions because every one of these
reads ``self.axes`` and the target hook, and threading those through by hand
would be four more places for a peer's copy to diverge.
"""

from dataclasses import dataclass, replace

from ..domain.board import MOVES, BoardState, Move, Position
from ..domain.rules import target_of
from ..domain.search import reachable_area
from .base import BrainBase, NoLegalActionError


def manhattan(a: Position, b: Position) -> int:
    """Steps between two cells, ignoring barriers.

    Admissible for orthogonal movement with no diagonals: it never
    overestimates, because every step changes exactly one coordinate by one.
    """
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


@dataclass
class PursuitRanking(BrainBase):
    """Chases a target cell, breaking ties by containment value."""

    def target(self, state: BoardState, **context: object) -> Position:
        """The cell to pursue.

        Runtime supplies the belief peak. Direct callers that omit it receive a
        deterministic uniform-prior choice derived only from board geometry;
        exact opponent truth is never a fallback.
        """
        supplied = context.get("target")
        if isinstance(supplied, tuple) and len(supplied) == 2:
            return (int(supplied[0]), int(supplied[1]))
        candidates = [
            (row, col)
            for row in range(state.grid_size)
            for col in range(state.grid_size)
            if (row, col) != state.cop and state.is_free((row, col))
        ]
        if not candidates:
            raise NoLegalActionError("belief prior has no possible thief cell")
        return candidates[0]

    def _pick_move(self, state: BoardState, **context: object) -> Move:
        """The legal move that gets closest to the target.

        Ties are broken by :data:`~..domain.board.MOVES` order rather than
        randomly, so two peers replaying the same match reach the same move.
        Better tie-breaking — containment value — is a later refinement, and
        this ordering is what it will replace.

        Raises:
            NoLegalActionError: if no move is legal.
        """
        available = self.options(state)
        if not available:
            raise NoLegalActionError("cop has no legal move")
        goal = self.target(state, **context)
        return min(available, key=lambda move: self._rank(state, move, goal))

    def _rank(self, state: BoardState, move: Move, goal: Position) -> tuple[int, int, int, int]:
        """Order candidates: distance first, then containment value.

        Returned as a tuple so ``min`` applies the criteria in priority order
        and the final element keeps the ordering total — two candidates that
        tie on everything else resolve by :data:`~..domain.board.MOVES` index,
        which is stable across peers and therefore replay-safe.
        """
        destination = target_of(state.cop, move, self.axes)
        distance = manhattan(destination, goal)
        after = replace(state, cop=destination)
        escape = reachable_area(after, goal, self.axes)
        edge = self._edge_pressure(state, goal)
        return (distance, escape, edge, MOVES.index(move))

    def _edge_pressure(self, state: BoardState, goal: Position) -> int:
        """How far the target sits from the nearest board edge.

        Lower is better for us: a target near an edge is one enclosure can
        close with two or three barriers instead of four. Used only when
        reachability cannot separate two candidates, which on an open board is
        most of the time.
        """
        row, col = goal
        last = state.grid_size - 1
        return min(row, col, last - row, last - col)
