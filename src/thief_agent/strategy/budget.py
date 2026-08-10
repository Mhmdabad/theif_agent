"""Spending the fourteen barriers.

The quota is a *minimum* in Appendix F, so it may be negotiated upward but
never assumed larger. Fourteen barriers across thirty-five turns means the
question is never "is this wall good" but "is this wall good enough to be one
of fourteen", and those have different answers.

**Spend rate follows belief concentration.** A barrier placed against a diffuse
belief is a guess: it seals a cell the thief probably is not near, and it is
gone permanently. As belief sharpens the same barrier becomes an investment,
because it constrains a region the thief demonstrably occupies. So the value a
placement must deliver to be worth spending is high while belief is spread and
falls as it concentrates.

**A reserve is held back.** Running out of barriers with the thief cornered is
the one way to lose this game to arithmetic: enclosure costs two barriers in a
corner and four in the open, so a cop holding one barrier cannot finish a
capture it has spent thirteen barriers setting up. The reserve is not spendable
until the position is one the reserve could actually close.

The reserve is the part of this module that has teeth. The spend rate shapes
play; the reserve prevents a specific, self-inflicted, unrecoverable loss.
"""

import math
from dataclasses import dataclass

from ..domain.actions import DEFAULT_MAX_BARRIERS
from ..domain.axes import AxisConvention
from ..domain.board import BoardState, Position
from ..domain.search import reachable_area

RESERVE = 3
"""Barriers withheld for the closing squeeze.

Three rather than two, because three is what an *edge* enclosure costs. Two
only suffices in a corner, and a reserve sized for the cheapest case is a
reserve that runs out in every other one.
"""

ENDGAME_AREA = 8
"""Escape area at or below which the reserve unlocks.

The reserve exists to finish a squeeze, so it becomes spendable exactly when
there is a squeeze to finish — not at a step count, which would let the clock
release it while the thief still roams an open board.
"""

DIFFUSE_DEMAND = 6
"""Escape reduction a placement must deliver when belief is at its most spread.

Roughly a corridor rather than a cell. Against a diffuse belief anything less
is paying a permanent cost for a guess.
"""


@dataclass(frozen=True, slots=True)
class Budget:
    """What is left of the quota, and what may be spent from it."""

    used: int
    limit: int = DEFAULT_MAX_BARRIERS
    reserve: int = RESERVE

    @property
    def remaining(self) -> int:
        """Barriers still available under the quota."""
        return max(0, self.limit - self.used)

    @property
    def spendable(self) -> int:
        """Barriers available *outside* the reserve."""
        return max(0, self.remaining - self.reserve)

    def may_spend(self, endgame: bool) -> bool:
        """Whether a barrier may be spent at all this turn.

        Outside the endgame the reserve is untouchable, so this is false as
        soon as only the reserve is left. That is the point: the cop stops
        placing barriers while it still has some.
        """
        if self.remaining <= 0:
            return False
        return endgame or self.spendable > 0

    def required_value(self, concentration: float) -> int:
        """The escape reduction a placement must beat to be worth a barrier.

        Falls linearly from :data:`DIFFUSE_DEMAND` to 1 as belief sharpens.
        Never zero — a barrier that reduces nothing is never worth spending,
        however certain we are about where the thief is.
        """
        sharpness = min(1.0, max(0.0, concentration))
        return max(1, math.ceil(DIFFUSE_DEMAND * (1.0 - sharpness)))

    def __str__(self) -> str:
        return (
            f"budget: {self.used}/{self.limit} used, "
            f"{self.spendable} free + {min(self.reserve, self.remaining)} reserved"
        )


def looks_like_endgame(state: BoardState, axes: AxisConvention, target: Position) -> bool:
    """Whether the position is a squeeze the reserve could finish.

    Measured from the room the thief has left rather than from the turn
    number. A clock-based unlock would hand the reserve over on turn thirty
    with the thief loose in open board, which is precisely the situation the
    reserve was withheld for.
    """
    return reachable_area(state, target, axes) <= ENDGAME_AREA


def worth_spending(value: int, budget: Budget, concentration: float, endgame: bool) -> bool:
    """Whether a placement worth ``value`` justifies a barrier right now."""
    if not budget.may_spend(endgame):
        return False
    return value >= budget.required_value(concentration)
