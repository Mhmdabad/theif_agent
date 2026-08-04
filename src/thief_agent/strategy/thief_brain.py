"""The thief's decision-making.

Evade the pursuer, breaking ties by **local openness** rather than position.

Distance alone is a trap. A thief maximising distance walks happily into a
corner, because a corner is often the furthest cell from the cop *and* the
place where enclosure costs two barriers instead of four. Running away and
running out of room look identical to a distance metric.

What the thief actually needs is somewhere to go for thirty-five turns, not
merely to be far away now. The obvious way to measure that is reachable area
after the step — and it does not work, for a reason worth stating plainly
because the code carried it as a live tie-break for two issues.

**Reachable area cannot rank moves.** A move changes nothing but the thief's
own cell, so every legal destination is one step from the thief and therefore
in the thief's own connected component; reachable area is a property of that
component, so it returns the same number for every candidate. Always. Not
usually — a sweep of four thousand random positions found zero where it
differed. As a per-candidate term it was noise with a plausible name.

**Local degree** is the signal that does discriminate. Appendix D prices
enclosure by it: two barriers to seal a corner, three on an edge, four in the
open. Stepping onto a degree-2 cell hands the cop a capture at half price, and
it does so before any barrier exists, so nothing else has noticed yet.

**Reachable area still matters — over time rather than across candidates.**
Barriers are permanent, so the region can only shrink, and the rate at which
it shrinks is the cop's containment plan becoming visible. That is a signal
about the *state*, not about any one move, and :mod:`.containment` tracks it.
When the region is closing, degree is promoted above distance: the goal stops
being to get far away and becomes to get somewhere open, because distance
bought inside a pocket the cop is sealing buys nothing at all.

Degree enters the ranking twice. As a **veto** it outranks distance, which is
the module's one deliberately counter-intuitive ordering; it is held honest by
an exemption, because a cramped cell that *strictly increases* distance is a
genuine escape and refusing it means being caught in open board instead. As a
**preference** it ranks equal-distance candidates, which is what the exemption
leaves undecided — and where corner drift would otherwise walk straight back in
through the rule written to stop it.
"""

import logging
from dataclasses import dataclass, field, replace

from ..domain.axes import AxisConvention
from ..domain.board import MOVES, Agent, BoardState, Move, Position
from ..domain.rules import target_of
from .base import BrainBase, NoLegalActionError
from .containment import ContainmentTracker

logger = logging.getLogger(__name__)

MIN_OPEN_NEIGHBOURS = 3
"""Below this many open exits, a cell counts as cramped.

Three rather than two, so the four corners of an open board are already
refused. A corner has degree 2 and costs the cop two barriers; waiting for
degree to fall to 1 means waiting until one of those barriers is placed, by
which point the choice of whether to be there has been made.
"""


def manhattan(a: Position, b: Position) -> int:
    """Steps between two cells, ignoring barriers."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def open_neighbours(state: BoardState, cell: Position, axes: AxisConvention) -> int:
    """How many orthogonal steps out of ``cell`` lead somewhere free.

    The board edge and a barrier close a side equally, which is the whole of
    Appendix D's enclosure pricing: a cell needs four closed sides, and the
    board supplies the difference for nothing.
    """
    return sum(1 for move in MOVES if move != "STAY" and state.is_free(target_of(cell, move, axes)))


@dataclass
class ThiefBrain(BrainBase):
    """Evades the pursuer, refusing cramped cells that gain nothing."""

    min_open_neighbours: int = MIN_OPEN_NEIGHBOURS
    reach: ContainmentTracker = field(default_factory=ContainmentTracker)

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
        """The best legal move under :meth:`_rank`.

        Not simply the furthest: degree can veto a step and can decide between
        equally distant ones. Whatever survives that, ties break by
        :data:`~..domain.board.MOVES` order rather than randomly, so two peers
        replaying the same match reach the same move.

        The seed goes out on every line rather than once at startup. A match
        transcript is the artefact a bug report is reconstructed from, and a
        seed recorded only in a line that may have been truncated, rotated or
        never captured is a seed the reproduction does not have.

        Raises:
            NoLegalActionError: if no move is legal.
        """
        available = self.options(state)
        if not available:
            raise NoLegalActionError("thief has no legal move")
        self.reach.observe(state, self.axes)
        logger.info("step %d seed=%d %s", state.step, self.seed, self.reach)
        threat = self.threat(state, **context)
        return max(available, key=lambda move: self._rank(state, move, threat))

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
