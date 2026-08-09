"""Alpha-beta search over a board where both pieces are known.

The game is partially observable, so this is only half an answer: it searches
a *hypothesis* — "suppose the opponent is exactly here" — and
:mod:`.scenarios` is what turns a belief into the set of hypotheses worth
searching. Keeping the two apart means the search is an ordinary, testable
minimax with no probability in it, and the uncertainty lives in one place.

**Fixed depth, never a time budget.** Iterative deepening to a wall clock is
the usual way to spend an allowance, and it is wrong here: the same position
would search deeper on a fast machine and pick a different move, so a match
would stop being replayable and ``test_determinism`` would be asserting
something the engine no longer provides. Depth is a number, and the same
position always returns the same move.

**Both roles search the same tree.** The cop maximises capture and the thief
maximises survival, which are the same function with the sign flipped — so
one negamax carries both, and the role-specific judgement stays entirely
inside the evaluator each brain supplies.

Move ordering is by the evaluator at depth one, best first. That is what makes
the pruning worth having: on this branching factor a good first move cuts most
of the tree, and a bad one searches all of it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .actions import Action, apply_action
from .axes import AxisConvention
from .board import Agent, BoardState
from .outcome import is_capture_by_overlap, is_enclosure_capture, is_trapping_capture

__all__ = ["WIN", "Search", "captured", "opponent_of"]

WIN = 1_000_000.0
"""Terminal score. Large enough that no heuristic sum can rival a capture."""

Evaluate = Callable[[BoardState, Agent], float]


def opponent_of(agent: Agent) -> Agent:
    return "cop" if agent == "thief" else "thief"


def captured(state: BoardState, axes: AxisConvention) -> bool:
    """Any of the rulebook's three capture conditions."""
    return (
        is_capture_by_overlap(state)
        or is_trapping_capture(state)
        or is_enclosure_capture(state, axes)
    )


@dataclass(frozen=True, slots=True)
class Search:
    """A depth-limited negamax with alpha-beta pruning."""

    axes: AxisConvention
    evaluate: Evaluate
    actions: Callable[[BoardState, Agent], Sequence[Action]]
    depth: int = 4

    def best(self, state: BoardState, me: Agent) -> Action | None:
        """The action with the highest searched value, or ``None`` if none is legal.

        Ties break on the order ``actions`` returns, which every caller keeps
        stable — so the choice is total and the match stays replayable.
        """
        best_action, best_score = None, -WIN * 2
        for action in self._ordered(state, me):
            score = self.value_of(state, me, action)
            if score > best_score:
                best_action, best_score = action, score
        return best_action

    def value_of(self, state: BoardState, me: Agent, action: Action) -> float:
        """What taking ``action`` here is worth to ``me``, searched in full.

        The per-action entry point a brain that scores candidates itself needs
        — it plays the action, then hands the rest of the tree to the opponent
        exactly as :meth:`best` does, so the two can never disagree.
        """
        return -self._negamax(
            self._advance(state, me, action),
            opponent_of(me),
            self.depth - 1,
            -WIN * 2,
            WIN * 2,
        )

    def _ordered(self, state: BoardState, me: Agent) -> list[Action]:
        """Candidates, most promising first, to make the pruning bite."""
        scored = [
            (self.evaluate(self._advance(state, me, action), me), index, action)
            for index, action in enumerate(self.actions(state, me))
        ]
        return [action for _, _, action in sorted(scored, key=lambda row: (-row[0], row[1]))]

    def _advance(self, state: BoardState, agent: Agent, action: Action) -> BoardState:
        """One ply. Illegal actions never reach here; callers only offer legal ones."""
        return apply_action(state, agent, action, self.axes)

    def _negamax(
        self, state: BoardState, turn: Agent, depth: int, alpha: float, beta: float
    ) -> float:
        """Value of ``state`` to ``turn``, searching ``depth`` further plies.

        Capture is checked before depth: a line that ends the game ends the
        search, and reporting a heuristic for a finished board would let the
        engine trade a capture for a rounding error.
        """
        if captured(state, self.axes):
            # Whoever is to move has already lost if the thief is taken.
            return -WIN if turn == "thief" else WIN
        if depth <= 0:
            return self.evaluate(state, turn)
        best = -WIN * 2
        for action in self.actions(state, turn):
            score = -self._negamax(
                self._advance(state, turn, action), opponent_of(turn), depth - 1, -beta, -alpha
            )
            best = max(best, score)
            alpha = max(alpha, score)
            if alpha >= beta:
                break
        return best if best > -WIN * 2 else self.evaluate(state, turn)
