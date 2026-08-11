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
from ..domain.rules import legal_moves, target_of
from ..domain.scenarios import blend, likeliest
from .thief_brain import ThiefBrain

__all__ = ["SearchingThief"]

DEPTH = 4
"""Plies per hypothesis: two moves each. Where a sealing manoeuvre first
becomes visible, and cheap enough on this branching factor to leave the turn
deadline untouched. *Negotiable tuning, not an Appendix F value.*"""


RETREAD = 2.0
"""Value charged per recent visit to a candidate cell.

Between ``DISTANCE`` and ``DEGREE``: enough that a two-cell bounce loses to a
step onto fresh ground, far below ``AREA``, so room still decides.
"""


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

        **The tracker is fed here, not only by the inherited path.** Overriding
        this method skipped the one call recording where we have been, so this
        brain played every match with an empty history: ``visits`` read zero and
        ``closing`` never fired. Idempotent per step, so the fallback path
        recording it again is a no-op.
        """
        self.reach.observe(state, self.axes)
        options = legal_moves(state, "thief", self.axes)
        hypotheses = self._hypotheses(state, context)
        if not options or not hypotheses:
            return super()._pick_move(state, **context)
        engine = self._engine()
        scored = [
            (
                self._value(engine, state, move, hypotheses) - self._retread(state, move),
                -MOVES.index(move),
                move,
            )
            for move in options
        ]
        return max(scored)[2]

    def _retread(self, state: BoardState, move: Move) -> float:
        """What returning to our own bright ground costs, in the search's units.

        **The evaluation cannot see this and never could.**
        :func:`~..domain.lookahead_eval.evaluate` is a pure function of a board,
        and nothing in a board says where the thief has *been* — so two
        geometrically identical cells score identically, and from ``(5, 5)``
        stepping north looks best while from ``(4, 5)`` stepping south does. The
        shipped thief bounced between those two from step 13 to capture in every
        sub-game, not because the bounce was cheap but because it was
        **invisible**.

        Priced here rather than inside ``evaluate`` because it is not a property
        of the position: the same square is expensive to us and free to an
        opponent who has never stood on it. A term in the shared evaluator would
        have to lie to one of the two sides the negamax alternates between.

        Weighted at :data:`RETREAD` per recent visit, so it trades against
        distance without overriding room: a thief fleeing its own scent into a
        pocket has swapped a slow loss for a fast one.
        """
        return RETREAD * self.reach.visits(target_of(state.thief, move, self.axes))

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
