"""The thief's decision-making.

Evade the pursuer, breaking ties by **escape space** rather than position.

Distance alone is a trap. A thief maximising distance walks happily into a
corner, because a corner is often the furthest cell from the cop *and* the
place where enclosure costs two barriers instead of four. Running away and
running out of room look identical to a distance metric.

So candidates that tie on distance are ranked by the number of free cells still
reachable afterwards. That is the quantity the thief actually needs: survival
requires somewhere to go for thirty-five turns, not merely being far away now.

Reachable area is not enough on its own, because on an open board every
candidate reaches the same cells and the metric goes quiet exactly when the
corner problem is worst. **Local degree** — how many orthogonal neighbours are
still open — is the missing signal. Appendix D prices enclosure by degree: two
barriers to seal a corner, three on an edge, four in the open. Stepping onto a
degree-2 cell hands the cop a capture at half price, and it does so before any
barrier exists, so nothing else in the ranking has noticed yet.

Degree enters the ranking twice. As a **veto** it outranks distance, which is
the module's one deliberately counter-intuitive ordering; it is held honest by
an exemption, because a cramped cell that *strictly increases* distance is a
genuine escape and refusing it means being caught in open board instead. As a
**preference** it ranks equal-distance candidates, which is what the exemption
leaves undecided — and where corner drift would otherwise walk straight back in
through the rule written to stop it.
"""

from dataclasses import dataclass, replace

from ..domain.axes import AxisConvention
from ..domain.board import MOVES, Agent, BoardState, Move, Position
from ..domain.rules import target_of
from ..domain.search import reachable_area
from .base import BrainBase, NoLegalActionError

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

        Raises:
            NoLegalActionError: if no move is legal.
        """
        available = self.options(state)
        if not available:
            raise NoLegalActionError("thief has no legal move")
        threat = self.threat(state, **context)
        return max(available, key=lambda move: self._rank(state, move, threat))

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

    def _rank(
        self, state: BoardState, move: Move, threat: Position
    ) -> tuple[int, int, int, int, int]:
        """Order candidates. Degree appears twice, and both times earn it.

        ``roomy`` is the **veto**, and it sits above distance — the one
        ordering here that looks wrong and is not. Distance is what the thief
        wants; degree is what the thief needs in order to still want it in ten
        turns. A cop closes a corner with two barriers and open board with
        four, so a step that halves the price of capturing us is worse than a
        step that is one cell nearer. :meth:`is_cramped` exempts a cramped cell
        that strictly gains ground, so a real escape is never refused.

        ``degree`` is the **preference**, and it sits below distance because
        the exemption alone leaves a hole. From (1, 0) with the threat at
        (1, 4), N to the corner and S to open board both gain a cell, so both
        are exempt, both reach all 49 cells, and the tie fell through to
        ``MOVES`` order — which picked the corner. That is the drift this issue
        is about, arrived at through the rule meant to prevent it. Ranking
        equal-distance candidates by raw degree is #37's stated acceptance
        criterion and closes the hole without weakening the exemption.

        Returned as a tuple so ``max`` applies the criteria in priority order,
        ending in the negated :data:`~..domain.board.MOVES` index. That keeps
        the ordering total — two candidates never tie completely, so the choice
        stays deterministic and a match remains replayable.
        """
        destination = target_of(state.thief, move, self.axes)
        roomy = 0 if self.is_cramped(state, move, threat) else 1
        distance = manhattan(destination, threat)
        after = replace(state, thief=destination)
        degree = open_neighbours(after, destination, self.axes)
        room = reachable_area(after, destination, self.axes)
        return (roomy, distance, degree, room, -MOVES.index(move))
