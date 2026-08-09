"""How the thief orders the moves available to it.

The scoring half of the policy: what a candidate is worth, what it costs to
sit still, and which cells are refused outright. Kept apart from
:mod:`.thief_brain`, which decides *whose* threat is being ranked against and
picks the winner; this module only says which of two candidates is better.

Abstract on purpose. :class:`ThiefRanking` supplies the criteria and leaves
:meth:`~.base.BrainBase.role` and ``_pick_move`` to the brain that uses them,
so the ordering cannot be instantiated and consulted without a policy around
it.
"""

from dataclasses import dataclass, field, replace

from ..domain.board import MOVES, BoardState, Move, Position
from ..domain.rules import target_of
from .base import BrainBase
from .containment import ContainmentTracker
from .thief_brain_geometry import MIN_OPEN_NEIGHBOURS, manhattan, open_neighbours

__all__ = ["ThiefRanking"]


@dataclass
class ThiefRanking(BrainBase):
    """Scores candidate moves by distance, degree and scent.

    The criteria a thief chooses with; :class:`~.thief_brain.ThiefBrain` adds
    the role, the threat and the choice itself.
    """

    min_open_neighbours: int = MIN_OPEN_NEIGHBOURS
    reach: ContainmentTracker = field(default_factory=ContainmentTracker)

    def scent_cost(self, move: Move) -> int:
        """What standing still costs in signal, measured in cells of distance.

        Survival is the win condition, so waiting is a real option — but it is
        not a free one. The thief emits at its own cell every turn while decay
        removes only a tenth, so a cell sat on for three turns carries a
        signal a cell walked through never reaches. That is a beacon, and a
        beacon is negative distance: it is exactly the quantity that converts
        the cop's search into a heading.

        Charged only to ``STAY``, and only for turns *already* spent here, so
        arriving somewhere and pausing once is free. Camping is not.
        """
        return self.reach.linger if move == "STAY" else 0

    def is_cramped(self, state: BoardState, move: Move, threat: Position) -> bool:
        """Whether ``move`` walks into a corner without earning it.

        Two conditions, and the second is what stops this from being a rule
        against ever entering a corner. A cell below the degree threshold is
        only refused when the step does **not strictly increase** distance from
        the threat: a cramped cell that genuinely gains ground is an escape,
        and the thief that will not take it gets caught in open board instead.
        What is refused is drifting into low-degree ground for nothing.
        """
        destination = target_of(state.thief, move, self.axes)
        if manhattan(destination, threat) > manhattan(state.thief, threat):
            return False
        after = replace(state, thief=destination)
        return open_neighbours(after, destination, self.axes) < self.min_open_neighbours

    def _rank(self, state: BoardState, move: Move, threat: Position) -> tuple[int, int, int, int]:
        """Order candidates. Degree appears twice, and both times earn it.

        ``roomy`` is the **veto**, and it sits above distance — the one
        ordering here that looks wrong and is not. Distance is what the thief
        wants; degree is what the thief needs in order to still want it in ten
        turns. A cop closes a corner with two barriers and open board with
        four, so a step that halves the price of capturing us is worse than a
        step that is one cell nearer. :meth:`is_cramped` exempts a cramped cell
        that strictly gains ground, so a real escape is never refused.

        ``degree`` is the **preference**. Normally it sits below distance,
        breaking ties the exemption leaves open: from (1, 0) with the threat at
        (1, 4), N to the corner and S to open board both gain a cell, so both
        are exempt, and the tie used to fall through to ``MOVES`` order — which
        picked the corner. That is corner drift arrived at through the rule
        written to prevent it.

        When the tracker reports the region **closing**, degree and distance
        swap. Inside a pocket the cop is sealing, distance is worthless: the
        cop does not need to enter the pocket, only to finish the wall, so a
        thief maximising distance retreats into the closing end of its own
        trap. Heading for open ground instead — even a step toward the pursuer
        — is what leaving early looks like, and leaving early is the only kind
        of leaving a closing region permits.

        The veto stays on top through both orderings. A trap is exactly the
        situation in which a cramped cell is most tempting and most fatal.

        ``distance`` is charged the scent cost of the move before it is
        compared, so ``STAY`` competes on what waiting actually buys. It is a
        candidate like any other — survival, not distance, is the win
        condition, and waiting is sometimes optimal — but each turn already
        spent on a cell makes the next one cost another cell of effective
        distance. A thief that camps is a thief broadcasting its address.

        Returned as a tuple so ``max`` applies the criteria in priority order,
        ending in the negated :data:`~..domain.board.MOVES` index. That keeps
        the ordering total — two candidates never tie completely, so the choice
        stays deterministic and a match remains replayable.
        """
        destination = target_of(state.thief, move, self.axes)
        roomy = 0 if self.is_cramped(state, move, threat) else 1
        distance = manhattan(destination, threat) - self.scent_cost(move)
        after = replace(state, thief=destination)
        degree = open_neighbours(after, destination, self.axes)
        if self.reach.closing:
            return (roomy, degree, distance, -MOVES.index(move))
        return (roomy, distance, degree, -MOVES.index(move))
