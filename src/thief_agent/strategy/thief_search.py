"""A searching thief: expectimax over the belief, exact minimax inside it.

The shipped :class:`~.thief_brain.ThiefBrain` ranks the five candidate moves
by a lexicographic heuristic and takes the best. It is sound and it is one
ply: it cannot see that the roomy cell it prefers is the mouth of a corridor
the cop seals in two moves, because seeing that means playing the cop's
replies out.

This brain plays them out. For each of the likeliest cells the cop might
occupy it runs an alpha-beta search of the fully-observable game
(:mod:`..domain.lookahead`), then blends the results by how likely each
hypothesis was — the average for what usually happens, the worst case for what
we cannot afford (:mod:`..domain.scenarios`).

**It inherits rather than replaces.** The legality guard, the containment
tracker, the seeded determinism and the hint layer are the shipped brain's and
are untouched; only the move choice is overridden, and it defers to the
inherited ranking whenever the search has nothing to work with. A search that
falls back to a good heuristic is strictly better than one that gambles.

**Deterministic.** Fixed depth, no clock, no randomness, total ordering. A
match that cannot be replayed cannot be audited, and ``test_determinism``
holds the line.
"""

from dataclasses import dataclass, replace

from ..domain.actions import MoveAction
from ..domain.board import MOVES, BoardState, Move, Position
from ..domain.lookahead import Search
from ..domain.lookahead_eval import evaluate
from ..domain.lookahead_moves import candidates
from ..domain.rules import legal_moves
from ..domain.scenarios import blend, likeliest
from .thief_brain import ThiefBrain

__all__ = ["SearchingThief"]

DEPTH = 4
"""Plies per hypothesis: two moves each. Where a sealing manoeuvre first
becomes visible, and cheap enough on this branching factor to leave the turn
deadline untouched. *Negotiable tuning, not an Appendix F value.*"""


@dataclass
class SearchingThief(ThiefBrain):
    """A thief that searches the cop's replies before committing to a move."""

    depth: int = DEPTH
    max_barriers: int = 14

    def _pick_move(self, state: BoardState, **context: object) -> Move:
        """The move that survives the cop's best replies across the belief.

        Falls back to the inherited ranking when the belief offers nothing to
        search — an empty distribution at the opening of a sub-game — because
        a one-ply heuristic beats an arbitrary choice.
        """
        options = legal_moves(state, "thief", self.axes)
        hypotheses = self._hypotheses(state, context)
        if not options or not hypotheses:
            return super()._pick_move(state, **context)
        engine = self._engine()
        scored = [
            (self._value(engine, state, move, hypotheses), -MOVES.index(move), move)
            for move in options
        ]
        return max(scored)[2]

    def _engine(self) -> Search:
        """The search this brain runs, rebuilt per turn from live settings."""
        return Search(
            axes=self.axes,
            evaluate=lambda board, turn: evaluate(board, self.axes, turn),
            actions=lambda board, agent: candidates(board, agent, self.axes, self.max_barriers),
            depth=self.depth,
        )

    def _hypotheses(
        self, state: BoardState, context: dict[str, object]
    ) -> list[tuple[Position, float]]:
        """Where the cop might be, and how likely each cell is.

        The runtime substitutes the belief peak into ``state.cop``; when it
        also passes the spread, the search plans against the distribution
        rather than against its mode alone. The peak is the fallback, which is
        exactly the point-mass case of the same computation.
        """
        spread = context.get("belief")
        if isinstance(spread, dict) and spread:
            return likeliest({cell: float(mass) for cell, mass in spread.items()}, state)
        return [(state.cop, 1.0)]

    def _value(
        self,
        engine: Search,
        state: BoardState,
        move: Move,
        hypotheses: list[tuple[Position, float]],
    ) -> float:
        """One move's blended value across every hypothesis about the cop."""
        return blend(
            [
                (engine.value_of(replace(state, cop=cell), "thief", MoveAction(move)), weight)
                for cell, weight in hypotheses
            ]
        )
