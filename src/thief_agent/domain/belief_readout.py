"""Reading a belief distribution without disturbing it.

The query half of :mod:`.belief`: the accessors and the derived figures the
policy and the GUI ask for, none of which change the mass. Separated from the
machinery that *maintains* the invariants — normalisation, barrier zeroing,
the Bayes step — so that the code enforcing "sums to one, zero on barriers,
never negative" sits in one place, read without the readouts in the way.

Mixed into :class:`~.belief.Belief` rather than kept as loose functions over a
mapping, so there is still exactly one object: the cell the strategy targets
and the grid the heatmap paints are read off the same distribution, by the
same code, and cannot drift apart.
"""

from .board import Position


class BeliefReadout:
    """The read-only surface of a belief distribution."""

    grid_size: int
    mass: dict[Position, float]

    def at(self, cell: Position) -> float:
        """Probability the opponent is on ``cell``. Zero if sealed or unknown."""
        return self.mass.get(cell, 0.0)

    def total(self) -> float:
        """Should always be 1.0, or 0.0 if the board has no free cell."""
        return sum(self.mass.values())

    def most_likely(self) -> Position | None:
        """``argmax b(s)``: the cell the policy pursues.

        Ties break by position so two peers replaying a match agree, and so a
        uniform prior yields a stable target rather than a wandering one.
        """
        if not self.mass:
            return None
        return min(self.mass, key=lambda cell: (-self.mass[cell], cell))

    def concentration(self) -> float:
        """How sharply focused the belief is, in ``[0, 1]``.

        The peak's share of the total, rescaled so a uniform distribution
        reads 0 and certainty reads 1. This is the figure the barrier budget
        curve spends against: a wall placed on a diffuse belief is a permanent
        cost paid for a guess.
        """
        possible = [value for value in self.mass.values() if value > 0.0]
        if not possible:
            return 0.0
        if len(possible) == 1:
            return 1.0
        peak = max(possible)
        floor = 1.0 / len(possible)
        if peak <= floor:
            return 0.0
        return (peak - floor) / (1.0 - floor)

    def heatmap(self) -> list[list[float]]:
        """Row-major grid for the GUI. A view of this object, not a copy."""
        return [
            [self.at((row, col)) for col in range(self.grid_size)] for row in range(self.grid_size)
        ]
