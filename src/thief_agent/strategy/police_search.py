"""A searching cop: expectimax over the belief, exact minimax inside it.

The shipped :class:`~.police_brain.PoliceBrain` closes distance to the belief
peak and weighs a barrier against a move with a one-ply value call. It is
sound and it is one ply: it cannot see that the barrier it declines now is the
one that seals the corridor in three turns, because seeing that means playing
the thief's escapes out.

This brain plays them out. For each of the likeliest cells the thief might
occupy it searches the fully-observable game (:mod:`..domain.lookahead`), then
blends by how likely each hypothesis was — the average for what usually
happens, the worst case for the escape we cannot afford
(:mod:`..domain.scenarios`).

**The winning placement still short-circuits.** Rule 46's trapping capture is
checked first and unconditionally, exactly as the shipped brain does: a search
would find it too, but a capture available *now* should never depend on an
evaluation function being weighted correctly.

**It inherits rather than replaces.** The legality guard, the barrier quota,
the seeded determinism and the hint layer are the shipped brain's. Only the
action choice is overridden, and it defers to the inherited logic whenever the
search has nothing to work with.
"""

from dataclasses import dataclass, replace

from ..domain.actions import Action, PlaceBarrier
from ..domain.board import BoardState, Position
from ..domain.lookahead import Search
from ..domain.lookahead_eval import evaluate
from ..domain.lookahead_moves import candidates
from ..domain.scenarios import blend, likeliest
from .barriers import winning_placement
from .police_brain import PoliceBrain

__all__ = ["SearchingPolice"]

DEPTH = 4
"""Plies per hypothesis: two moves each. *Negotiable tuning, not Appendix F.*"""


@dataclass
class SearchingPolice(PoliceBrain):
    """A cop that searches the thief's escapes before committing to an action."""

    depth: int = DEPTH

    def _decide_move(self, state: BoardState, **context: object) -> Action:
        """The action that survives the thief's best escapes across the belief.

        The winning placement is taken without searching for it. Everything
        else is searched, and the inherited one-ply logic is the fallback when
        the belief offers no hypothesis worth the tree.
        """
        win = winning_placement(state, self.axes, self.max_barriers)
        if win is not None:
            return PlaceBarrier(win)
        hypotheses = self._hypotheses(state, context)
        if not hypotheses:
            return super()._decide_move(state, **context)
        chosen = self._best(state, hypotheses)
        if chosen is None:
            return super()._decide_move(state, **context)
        self._guard(state, chosen)
        return chosen

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
        """Where the thief might be, and how likely each cell is."""
        spread = context.get("belief")
        if isinstance(spread, dict) and spread:
            return likeliest({cell: float(mass) for cell, mass in spread.items()}, state)
        return [(state.thief, 1.0)]

    def _best(self, state: BoardState, hypotheses: list[tuple[Position, float]]) -> Action | None:
        """The highest-scoring legal action, or ``None`` when there is none.

        Ties break on the order :func:`~..domain.lookahead_moves.candidates`
        returns, which is fixed — so the choice is total and replayable.
        """
        engine = self._engine()
        options = candidates(state, "cop", self.axes, self.max_barriers)
        if not options:
            return None
        scored = [
            (
                blend(
                    [
                        (engine.value_of(replace(state, thief=cell), "cop", action), weight)
                        for cell, weight in hypotheses
                    ]
                ),
                -index,
                action,
            )
            for index, action in enumerate(options)
        ]
        return max(scored, key=lambda row: (row[0], row[1]))[2]
