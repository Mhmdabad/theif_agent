"""Catching a lie by checking it against the trail.

The rulebook's worked example (PDF p. 47) is the whole mechanism in one
paragraph. The thief announces "I moved north". Had that been true, the cop
would expect a fresh trace in the north of roughly

    (1 - rho) * 0.9 = 0.81

Instead it measures 0.00 there, while the entire scent mass sits at the
opposite pole of the board. The cop concludes, with high confidence, that the
thief is lying: it lowers the trust it assigns to verbal claims, re-weights
its probability matrix toward the south-east, and re-aims pursuit at the real
source rather than the declared one.

**The trail cannot lie.** It is emitted by movement itself and cannot be
forged. So what is exposed here is never a "false trail" — no such thing
exists — but a *verbal* claim caught contradicting the environment. The
asymmetry is the point: the liar's own physics testify against them, and the
attempt to mislead is what reveals the position.

**Absence of evidence is graded, not binary.** A claim is scored by the gap
between the intensity it predicts and the intensity measured, relative to what
was predicted. A claim about a cell we would expect to be faint anyway is weak
evidence either way; a claim about a cell that should be blazing and is silent
is close to proof. Scoring the ratio rather than the difference keeps a
prediction of 0.81 against 0.00 far more damning than 0.05 against 0.00.

The check is symmetric and both agents run it. The thief cross-checks the
cop's trail against the cop's hints by exactly this procedure.
"""

from dataclasses import dataclass

from .board import Position
from .trail import DECAY

FRESH_TRACE: float = round((1.0 - DECAY) * 0.9, 3)
"""What a one-turn-old trace of a full-strength emission should measure.

0.81 under the rulebook's multiplicative decay. This is the number the book's
worked example computes, and it is why the decay rule had to be settled before
the detector could be written: the reference implementation's subtraction
predicts 0.80, so an agent using it would compute a different expectation and
a different confidence from the same board.
"""

CONTRADICTION = 0.6
"""Gap, as a fraction of what was predicted, above which a claim is a lie.

The book's example sits at 1.0 — everything predicted, nothing measured. The
threshold is well below that so a claim only partly unsupported still counts,
and well above zero so ordinary decay noise does not.
"""


@dataclass(frozen=True, slots=True)
class Verdict:
    """One claim, checked against the field."""

    predicted: float
    measured: float
    cells: tuple[Position, ...]

    @property
    def gap(self) -> float:
        """How much of the predicted intensity is missing, in ``[0, 1]``."""
        if self.predicted <= 0.0:
            return 0.0
        return max(0.0, (self.predicted - self.measured) / self.predicted)

    @property
    def contradicted(self) -> bool:
        """Whether the environment refuses to support the claim."""
        return self.gap >= CONTRADICTION

    def __str__(self) -> str:
        state = "CONTRADICTED" if self.contradicted else "supported"
        return (
            f"{state}: predicted {self.predicted:.3f}, measured {self.measured:.3f}, "
            f"gap {self.gap:.0%} over {len(self.cells)} cell(s)"
        )


def check(
    claim: dict[Position, float],
    field: dict[Position, float],
    predicted: float = FRESH_TRACE,
) -> Verdict:
    """Score a claim against the opponent's sampled trail.

    ``claim`` is the set of cells the hint asserts the opponent occupies or
    has just left. The strongest measured intensity among them is compared
    with what a truthful claim would have deposited.

    The *strongest* rather than the mean, deliberately. A hint naming a region
    is honest if the opponent is anywhere in it, so requiring every cell to be
    hot would convict a truthful speaker of imprecision.
    """
    cells = tuple(sorted(claim))
    measured = max((field.get(cell, 0.0) for cell in cells), default=0.0)
    return Verdict(predicted=predicted, measured=measured, cells=cells)


def true_source(field: dict[Position, float]) -> Position | None:
    """Where the trail says the opponent actually is.

    What pursuit re-aims at once a claim is disbelieved: not the declared
    direction, and not the negation of it, but the real scent maximum.
    """
    if not field:
        return None
    return min(field, key=lambda cell: (-field[cell], cell))
