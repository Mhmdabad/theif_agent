"""Whose turn it is, and when a full turn has elapsed.

Two rules the rest of the system depends on:

**Strict alternation.** Acting out of turn is impossible by construction — the
scheduler names the agent to move, rather than being asked to approve a move
someone already chose.

**A step is a full turn.** Both sides having moved, not one. Scent decays on
that boundary and the survival count advances on it, so a scheduler that
counted half-moves would decay the board twice as fast and hand the thief a
survival win in half the required turns. That separation was introduced with
``advance_turn`` and is enforced here.
"""

from dataclasses import dataclass, field

from ..domain.board import Agent


class OutOfTurnError(RuntimeError):
    """Raised when an agent attempts to act outside its turn."""


@dataclass
class TurnScheduler:
    """Alternates the two agents and reports full-turn boundaries.

    The cop moves first: it starts in a corner while the thief starts central,
    so the opening move is the cop's to close distance. The order is a field
    rather than a constant because start positions are negotiable.
    """

    first: Agent = "cop"
    to_move: Agent = field(init=False)
    half_moves: int = 0
    completed_turns: int = 0

    def __post_init__(self) -> None:
        self.to_move = self.first

    @property
    def other(self) -> Agent:
        return "thief" if self.to_move == "cop" else "cop"

    def require_turn(self, agent: Agent) -> None:
        """Raise unless it is ``agent``'s turn.

        Raises:
            OutOfTurnError: naming both agents, so a log says who tried to act
                and who was owed the turn.
        """
        if agent != self.to_move:
            raise OutOfTurnError(f"{agent} acted out of turn; {self.to_move} is to move")

    def record(self, agent: Agent) -> bool:
        """Record that ``agent`` has moved and pass the turn.

        Returns:
            ``True`` if that completed a **full** turn — both sides having
            moved — which is the boundary scent decay and the survival count
            key off.

        Raises:
            OutOfTurnError: if it was not ``agent``'s turn.
        """
        self.require_turn(agent)
        self.half_moves += 1
        self.to_move = self.other
        if self.half_moves % 2 == 0:
            self.completed_turns += 1
            return True
        return False
