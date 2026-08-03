"""The thief's decision-making.

Evade the pursuer, breaking ties by **escape space** rather than position.

Distance alone is a trap. A thief maximising distance walks happily into a
corner, because a corner is often the furthest cell from the cop *and* the
place where enclosure costs two barriers instead of four. Running away and
running out of room look identical to a distance metric.

So candidates that tie on distance are ranked by the number of free cells still
reachable afterwards. That is the quantity the thief actually needs: survival
requires somewhere to go for thirty-five turns, not merely being far away now.
"""

from dataclasses import dataclass, replace

from ..domain.board import MOVES, Agent, BoardState, Move, Position
from ..domain.rules import target_of
from ..domain.search import reachable_area
from .base import BrainBase, NoLegalActionError


def manhattan(a: Position, b: Position) -> int:
    """Steps between two cells, ignoring barriers."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


@dataclass
class ThiefBrain(BrainBase):
    """Evades the pursuer by maximising Manhattan distance."""

    @property
    def role(self) -> Agent:
        return "thief"

    def threat(self, state: BoardState, **context: object) -> Position:
        """The cell to run from.

        Until the belief map exists this is the cop's actual position — the
        "blind" stage, proving the decision core under full information before
        uncertainty is layered on.
        """
        supplied = context.get("threat")
        if isinstance(supplied, tuple) and len(supplied) == 2:
            return (int(supplied[0]), int(supplied[1]))
        return state.cop

    def _pick_move(self, state: BoardState, **context: object) -> Move:
        """The legal move that gets furthest from the threat.

        Ties break by :data:`~..domain.board.MOVES` order rather than randomly,
        so two peers replaying the same match reach the same move. Escape-space
        tie-breaking is a later refinement and this ordering is what it
        replaces.

        Raises:
            NoLegalActionError: if no move is legal.
        """
        available = self.options(state)
        if not available:
            raise NoLegalActionError("thief has no legal move")
        threat = self.threat(state, **context)
        return max(available, key=lambda move: self._rank(state, move, threat))

    def _rank(self, state: BoardState, move: Move, threat: Position) -> tuple[int, int, int]:
        """Order candidates: distance first, then room to keep running.

        Returned as a tuple so ``max`` applies the criteria in priority order,
        ending in the negated :data:`~..domain.board.MOVES` index. That keeps
        the ordering total — two candidates never tie completely, so the choice
        stays deterministic and a match remains replayable.
        """
        destination = target_of(state.thief, move, self.axes)
        distance = manhattan(destination, threat)
        after = replace(state, thief=destination)
        room = reachable_area(after, destination, self.axes)
        return (distance, room, -MOVES.index(move))
