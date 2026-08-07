"""The belief map: where the hidden opponent probably is.

A probability distribution over every cell, summing to one. This is the object
the policy targets and the GUI heatmap renders, and it must be the *same*
object for both — a display-only copy would let the picture we show diverge
from the reasoning we did, which is the one thing the screenshot requirement
in the submission checklist exists to demonstrate.

**Zero on barriers, always.** Nobody can stand on a sealed cell, so belief
there is not merely unlikely, it is impossible. That distinction matters
because the mass has to go somewhere: zeroing without renormalising leaves a
distribution summing to less than one, and every downstream comparison then
silently measures a different total. Barriers are permanent and only ever
accumulate, so this happens repeatedly through a match rather than once.

**Uniform is the honest prior.** Before any evidence, every free cell is
equally likely. A prior that guessed — weighting the centre, or the opponent's
start — would be evidence we did not gather, and the belief map's whole job is
to distinguish what we know from what we assume.

The map deliberately does not know *how* evidence arrives. Scent and hints are
combined by the Bayes update, which multiplies this distribution by a
likelihood and renormalises; keeping that out of here means the invariants —
sums to one, zero on barriers, never negative — are enforced in one place and
hold no matter what evidence is fed in.
"""

from dataclasses import dataclass, field

from .board import BoardState, Position


def _cells(grid_size: int) -> list[Position]:
    return [(row, col) for row in range(grid_size) for col in range(grid_size)]


@dataclass
class Belief:
    """A normalised distribution over the board."""

    grid_size: int
    mass: dict[Position, float] = field(default_factory=dict)

    @classmethod
    def uniform(cls, state: BoardState) -> "Belief":
        """Equal probability on every free cell, zero on barriers."""
        belief = cls(grid_size=state.grid_size)
        free = [cell for cell in _cells(state.grid_size) if not state.is_barrier(cell)]
        share = 1.0 / len(free) if free else 0.0
        belief.mass = {cell: share for cell in free}
        return belief

    def at(self, cell: Position) -> float:
        """Probability the opponent is on ``cell``. Zero if sealed or unknown."""
        return self.mass.get(cell, 0.0)

    def total(self) -> float:
        """Should always be 1.0, or 0.0 if the board has no free cell."""
        return sum(self.mass.values())

    def normalise(self) -> None:
        """Rescale to sum to one.

        A distribution that does not sum to one is not merely untidy: every
        threshold and every comparison downstream is then measuring against a
        different total, and the error compounds silently as barriers land.

        Cells at zero are kept rather than dropped. They are still candidates
        — a cell disproved by this turn's evidence can be revived by the next
        — and :meth:`concentration` measures the peak against the number of
        candidates, so discarding them would make the belief look sharper
        every time evidence ruled something out.
        """
        total = self.total()
        if total <= 0.0:
            self.mass = {}
            return
        self.mass = {cell: value / total for cell, value in self.mass.items()}

    def apply_barriers(self, state: BoardState) -> None:
        """Move all belief off sealed cells and renormalise.

        Barriers accumulate through a match, so this runs repeatedly. Zeroing
        without renormalising would leak mass a little at a time.
        """
        self.mass = {cell: value for cell, value in self.mass.items() if not state.is_barrier(cell)}
        self.normalise()

    def exclude(self, cell: Position) -> None:
        """Remove one physically impossible opponent cell and renormalise."""
        if cell in self.mass:
            self.mass[cell] = 0.0
            self.normalise()

    def update(self, likelihood: dict[Position, float]) -> None:
        """Multiply by a likelihood and renormalise: one Bayes step.

        **A cell the evidence does not mention is multiplied by one, not by
        zero.** The rulebook is explicit that a cell which never absorbed
        scent, or whose scent has fully decayed, is *silence* — absent
        information rather than negative information. Treating a missing key
        as zero would read "no scent here" as "the opponent is certainly not
        here", which is false: the emission covers 25 cells out of 49, so most
        of the board goes unmentioned every turn and a single update would
        collapse the distribution onto whatever the field happened to touch.
        An explicit zero still annihilates, which is what barriers and
        disproved cells need.

        The map does not care where the likelihood came from. Keeping evidence
        out of here means the invariants are enforced in one place and hold
        whatever is fed in.
        """
        scaled = {cell: value * likelihood.get(cell, 1.0) for cell, value in self.mass.items()}
        if sum(scaled.values()) <= 0.0:
            return
        self.mass = scaled
        self.normalise()

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
