"""The board-wide scent field, and how it forgets.

:mod:`.scent` says what one emission looks like. This is the accumulated
memory it lands in — every deposit either side has made, merged, and faded
once per turn.

**Decay is multiplicative.** The rulebook (PDF p. 43) gives

    tau(t+1) = max(0, (1 - rho) * tau(t) + delta_tau)

with rho = 0.10, and p. 43 states the intent in words as well: the trail keeps
**90% of its value each turn**. Three independent parts of the book agree on
that reading — the formula, the prose, and the worked lie-detection example on
p. 47, which computes an expected fresh trace of `(1-rho) * 0.9 = 0.81`. The
professor's reference implementation subtracts instead (`tau - rho`, giving
0.80 and silence at turn nine), and that is a genuine divergence recorded in
the README contradictions table rather than a reading we get to pick.

The difference is not a rounding quibble. Subtraction gives every cell the same
lifetime regardless of strength, and empties the board on a fixed schedule.
Proportional decay makes a strong trace outlive a weak one, which is what makes
intensity mean *recency* — and recency is the entire basis for reading a
direction out of the field.

`(1 - rho)` is forgetting, `delta_tau` is the present being written, and the
`max(0, .)` clamp is why a silent cell means *absent information* rather than
*negative information*. There is no such thing as evidence the opponent was not
somewhere.

**Once per full turn, not per half-move.** Decay fires after both agents have
moved. Applying it twice a turn halves the trail's memory and would put us out
of step with an opponent who read the rule correctly — and the field is
hash-locked, so being out of step is not a weaker strategy, it is a dispute.

Precision is kept internally and rounded only on the wire. Rounding at every
step would pin small values in place forever: 0.001 decayed is 0.0009, which
rounds straight back to 0.001. Both peers multiply identical rounded inputs by
the same constant, so full-precision arithmetic stays reproducible without that
trap.
"""

from dataclasses import dataclass, field

from ..shared.appendix_f import book_value
from .board import Position
from .scent import PRECISION

DECAY: float = float(book_value("pheromones", "pheromone_decay"))  # type: ignore[arg-type]
"""Appendix F decay rate. *Fixed* - deviating disqualifies the team."""

RETENTION: float = 1.0 - DECAY
"""What a cell keeps each turn. The book states this side of it in words."""

VANISHED = 0.5 * 10**-PRECISION
"""Below this a cell transmits as 0.000, so it is dropped rather than kept.

Multiplicative decay never reaches zero, and a field that only ever grows
costs memory and log space for values nobody can read. Dropping at the wire's
own resolution keeps the pruning observable rather than arbitrary.
"""


@dataclass
class Trail:
    """Every scent intensity one peer knows about, and its age."""

    values: dict[Position, float] = field(default_factory=dict)

    def deposit(self, emission: dict[Position, float]) -> None:
        """Lay a fresh field into the trail, strongest value winning.

        Max-merge rather than addition. Two deposits on one cell do not make
        it twice as fragrant — intensity is a clock, not a quantity, and
        summing would let a pacing agent manufacture a peak brighter than any
        real emission and drag the opponent's argmax to it.
        """
        for cell, value in emission.items():
            if value > self.values.get(cell, 0.0):
                self.values[cell] = value

    def decay(self, rate: float = DECAY) -> None:
        """Age the whole field by one full turn.

        Called after both agents have moved. Cells that fade past the wire's
        resolution are dropped, since they are indistinguishable from silence
        to anyone reading the snapshot.
        """
        retained = 1.0 - rate
        faded = {}
        for cell, value in self.values.items():
            aged = max(0.0, value * retained)
            if aged >= VANISHED:
                faded[cell] = aged
        self.values = faded

    def intensity_at(self, cell: Position) -> float:
        """What we know about ``cell``. Zero means silence, not absence."""
        return self.values.get(cell, 0.0)

    def strongest(self) -> Position | None:
        """The most fragrant cell: the naive guess at where the opponent is.

        Ties break by position so two peers reading the same field name the
        same cell. A belief map supersedes this, but it is the signal the
        belief map is built from.
        """
        if not self.values:
            return None
        return min(self.values, key=lambda cell: (-self.values[cell], cell))

    def snapshot(self) -> dict[str, float]:
        """The wire form: ``{"r,c": intensity}``, rounded to three decimals.

        Rounding happens here and only here. It is what makes two
        implementations agree on a float, and the agreement is hashed into the
        pre-series lock, so it is an interoperability guarantee rather than
        display formatting.
        """
        return {
            f"{row},{col}": round(value, PRECISION)
            for (row, col), value in sorted(self.values.items())
            if round(value, PRECISION) > 0.0
        }
