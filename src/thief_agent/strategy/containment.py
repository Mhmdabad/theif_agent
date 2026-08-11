"""Watching the cop's containment plan take shape — and our own trail behind us.

Barriers are permanent, so the thief's reachable region can only ever shrink.
That makes its size over time a signal rather than a statistic: every drop is a
barrier that bit, and the pattern of drops is the cop's plan becoming visible.

Tracking the trend rather than the value is a matter of timing. A closing region
has a point after which leaving is impossible, and by then the area is small and
irrelevant — the decision that mattered was several turns earlier, when the only
evidence was that it had begun to shrink. Reacting to *how small* the region is
reacts too late by construction; reacting to *how fast* it closes gets out.

The same history answers a second question in :meth:`ContainmentTracker.visits`
— where we have been, and so where our own scent is still bright.

Observations are keyed by step and recorded once, so a decision stays
reproducible: a tracker drifting with how often it was consulted would break a
replay in a way no single-turn test would show.
"""

from dataclasses import dataclass, field

from ..domain.axes import AxisConvention
from ..domain.board import BoardState, Position
from ..domain.search import reachable_area

WINDOW = 3
"""Observations compared when reading the trend.

Short, so the signal arrives while leaving is still possible; long enough that
one barrier somewhere irrelevant does not read as a containment plan.
"""

FRESH = 8
"""Turns a cell stays bright enough that returning to it is worth avoiding.

Decay removes a tenth each turn, so a cell left eight turns ago still holds two
fifths of what we gave it — and the cop's belief is built from exactly that.
"""

SHRINK_THRESHOLD = 2
"""Cells lost across the window before the region counts as closing.

One cell is a wall going up somewhere the thief was never going. Two is a
direction.
"""


@dataclass(frozen=True, slots=True)
class Reach:
    """The thief's room to move at one point in the match."""

    step: int
    area: int
    barriers: int
    cell: Position


@dataclass
class ContainmentTracker:
    """Reachable area per turn, and whether it is being taken away."""

    history: list[Reach] = field(default_factory=list)

    def observe(self, state: BoardState, axes: AxisConvention) -> Reach:
        """Record this turn's reachable area, or return the existing record.

        Idempotent in ``state.step``: consulting it twice in one turn must not
        change what it says, or two peers would diverge on nothing more than how
        often each called it.

        **A step going backwards is a new sub-game, and clears the trail.** One
        brain plays every sub-game of its role while steps restart at 1, so
        without this the idempotence check matches the *previous* sub-game's
        entry and returns it — freezing the history at sub-game 1 and reporting
        cells from a board that no longer exists.
        """
        if self.history and state.step < self.history[-1].step:
            self.history.clear()
        for seen in self.history:
            if seen.step == state.step:
                return seen
        entry = Reach(
            step=state.step,
            area=reachable_area(state, state.thief, axes),
            barriers=len(state.barriers),
            cell=state.thief,
        )
        self.history.append(entry)
        return entry

    @property
    def area(self) -> int:
        """The most recently observed reachable area, or 0 before any turn."""
        return self.history[-1].area if self.history else 0

    def visits(self, cell: Position, window: int = FRESH) -> int:
        """How many of the last ``window`` turns were spent on ``cell``.

        **The meter :attr:`linger` should have been.** Emission is a field, so
        adjacent cells overlap and a two-cell bounce lights one neighbourhood
        nearly as brightly as standing still — yet ``linger`` counts
        *consecutive* turns and resets on any move, so that bounce read zero.
        The current turn is excluded, so arriving and pausing once stays free.
        """
        return sum(1 for entry in self.history[:-1][-window:] if entry.cell == cell)

    @property
    def linger(self) -> int:
        """Consecutive turns already spent on the current cell.

        Kept alongside :meth:`visits`: *consecutive* is the sharper signal for
        camping, which a window would blur against a passing revisit.
        """
        if not self.history:
            return 0
        here = self.history[-1].cell
        count = 0
        for entry in reversed(self.history[:-1]):
            if entry.cell != here:
                break
            count += 1
        return count

    @property
    def trend(self) -> int:
        """Change in reachable area across the window. Negative is closing.

        Zero with fewer than two observations: one measurement is a value, not
        a direction, and guessing at a direction from it would have the thief
        fleeing its own starting position.
        """
        if len(self.history) < 2:
            return 0
        window = self.history[-WINDOW:]
        return window[-1].area - window[0].area

    @property
    def closing(self) -> bool:
        """Whether the region is being walled in fast enough to act on."""
        return self.trend <= -SHRINK_THRESHOLD

    def __str__(self) -> str:
        if not self.history:
            return "reach: unobserved"
        state = "CLOSING" if self.closing else "steady"
        return (
            f"reach: area={self.area} trend={self.trend:+d} over {len(self.history)} turns {state}"
        )
