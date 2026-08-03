"""The thief's decision-making.

A first, deliberately transparent policy: maximise Manhattan distance from the
pursuer, and never relocate somewhere illegal. Escape-space scoring,
corner aversion and barrier-trend tracking arrive as separate changes on top.

Distance alone is a weak proxy and the tests say so. A thief that maximises
distance will happily run into a corner, because a corner can be far from the
cop and still be where enclosure costs two barriers instead of four. That is
the flaw the later refinements exist to fix, and it is worth seeing plainly
before it is fixed.
"""

from dataclasses import dataclass

from ..domain.board import Agent, BoardState, Move, Position
from ..domain.rules import target_of
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
        return max(
            available, key=lambda move: manhattan(target_of(state.thief, move, self.axes), threat)
        )
