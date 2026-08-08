"""The strategy module's contract.

This is where the grade lives. Everything else in the repository is
infrastructure both teams must build identically from the same rulebook; the
brain is the only place one agent can out-think another.

It plugs into the runtime at exactly one point — **after the incoming hint is
decoded, before the outgoing Commit is packed** — and everything between those
two points is the agent's intelligence: belief update, action choice, and the
deception text.

**The move is always chosen here, in Python.** Language models hallucinate in
Cartesian space: they confuse directions, distances and coordinates, and will
return an illegal or self-destructive action with complete confidence. The
model writes text and profiles the opponent's language; the algorithm owns
every spatial decision.

Two overrides exist because the cop has two kinds of turn. ``_pick_move``
chooses a relocation; ``_decide_move`` chooses between relocating and
forfeiting movement to place a barrier. This agent never places one, so it
overrides only the first and inherits the default.
"""

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..domain.actions import Action, MoveAction, PlaceBarrier
from ..domain.axes import AxisConvention
from ..domain.board import Agent, BoardState, Move
from ..domain.rules import legal_moves
from .base_types import Decision, NoLegalActionError, StrategyContextError

__all__ = ["BrainBase", "Decision", "NoLegalActionError", "StrategyContextError"]


@dataclass
class BrainBase(ABC):
    """Base for a peer's decision-making.

    Subclasses override :meth:`_pick_move`, and the cop additionally overrides
    :meth:`_decide_move` to choose barrier placements.

    Randomness is seeded and the seed recorded. Identical state plus identical
    config must yield an identical action, or a match cannot be replayed and a
    reported bug cannot be reproduced — both of which the audit depends on.
    """

    axes: AxisConvention = field(default_factory=AxisConvention)
    seed: int = 0
    rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    @property
    @abstractmethod
    def role(self) -> Agent:
        """Which side this brain plays."""

    def decide(self, state: BoardState, **context: object) -> Decision:
        """Choose this turn's action.

        The single entry point the runtime calls, positioned after hint decode
        and before Commit packing. Subclasses override the hooks below rather
        than this method, so the legality guard cannot be bypassed.

        At runtime ``state.cop`` is the belief peak, not private truth, and
        ``context`` contains stable ``threat``, ``concentration``, and
        ``uncertainty`` keys. Configured brains should accept ``**context``.

        Raises:
            NoLegalActionError: if nothing legal is available.
        """
        action = self._decide_move(state, **context)
        self._guard(state, action)
        return Decision(action=action, hint=self._hint(state, action, **context))

    def _hint(self, state: BoardState, action: Action, **context: object) -> str:
        """Supply one deterministic safe verbal hint for this accepted turn."""
        del state, action, context
        return "I am watching the streets"

    def _decide_move(self, state: BoardState, **context: object) -> Action:
        """Choose between relocating and any role-specific alternative.

        The default is to relocate. The cop overrides this to weigh a barrier
        placement against a move; the thief has no alternative and inherits it.
        """
        return MoveAction(self._pick_move(state, **context))

    @abstractmethod
    def _pick_move(self, state: BoardState, **context: object) -> Move:
        """Choose a relocation. This is the method a strategy overrides."""

    def options(self, state: BoardState) -> list[Move]:
        """Legal moves for this brain's role, in stable order."""
        return legal_moves(state, self.role, self.axes)

    def _guard(self, state: BoardState, action: Action) -> None:
        """Re-validate whatever a subclass produced.

        Defence in depth. Even a heuristic — or a model suggestion, under the
        mutually agreed exception — can produce something illegal, and catching
        it here costs a local error rather than a rejected move and a technical
        loss.

        Two different questions, and only the first is about this board.

        A **barrier is never legal for the thief**, in any position, under any
        configuration. Only the cop may forfeit movement to seal a cell, so
        there is nothing here to validate against the state — the action is
        refused because of who is taking it. Letting it through on the grounds
        that "placement legality belongs to the domain layer" is exactly the
        mistake this guard exists to prevent: the domain layer would reject it
        too, but only after it had gone out on the wire, where the cop rejects
        it and we take a technical loss worth zero to both sides.

        A **move** is checked against the legal set for this position.

        Raises:
            NoLegalActionError: if the action is not one the thief may take.
        """
        if isinstance(action, PlaceBarrier):
            raise NoLegalActionError(
                f"thief cannot place a barrier at {action.at}; only the cop may place barriers"
            )
        available = self.options(state)
        if not available:
            raise NoLegalActionError(f"{self.role} has no legal move")
        if action.move not in available:
            raise NoLegalActionError(
                f"{self.role} chose {action.move}, which is not among {available}"
            )
