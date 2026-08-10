"""What a candidate placement is worth, as a value rather than a verdict.

Split out of :mod:`.barriers` so that module keeps to the file-length budget.
This half owns the *record* — the three axes, the self-preservation gate that
reads them, and the single function that fills one in for a given cell.
:mod:`.barriers` owns the ranking built on top and re-exports every name here.

The gate stays a property of the record rather than a filter applied on the way
in, because a refused candidate still has to be scored and still has to appear
in the log. Dropping one silently would leave a match transcript showing a
barrier that went somewhere odd with no record of what was rejected or why.
"""

from dataclasses import dataclass, replace

from ..domain.axes import AxisConvention
from ..domain.belief import Belief
from ..domain.board import BoardState, Position
from ..domain.rules import legal_moves
from ..domain.search import reachable_area
from .barriers_geometry import chain_progress, severed_mass, still_reaches

SELF_PENALTY = 1000
"""Weight for cutting ourselves off. Large enough to dominate any real gain.

Not infinite: the score stays a number so candidates remain totally ordered
and the log shows *why* a placement lost rather than only that it was dropped.
"""


@dataclass(frozen=True, slots=True)
class BarrierScore:
    """One candidate placement, scored on all three axes.

    Kept as separate fields rather than a single total so the log can show the
    breakdown. A placement decision that cannot be explained after the fact is
    one we cannot debug from a match transcript.
    """

    at: Position
    escape_reduction: int
    chain: int
    disconnects: bool
    immobilises: bool = False
    severed_belief: float | None = None
    """Probability mass the seal removes, or ``None`` before belief exists."""

    @property
    def permitted(self) -> bool:
        """Whether the self-preservation constraint allows this placement.

        A hard gate, checked before the score is consulted at all. No escape
        reduction is worth being unable to reach the thief, and none is worth
        being unable to answer a turn.
        """
        return not (self.disconnects or self.immobilises)

    @property
    def value(self) -> float:
        """Escape reduction, weighted by belief when a belief map exists.

        Cells are what the flood fill counts; probability is what the barrier
        buys. A region twice the size but a tenth as likely is worth a fifth
        as much, and on a board with a live belief map the largest regions are
        frequently the emptiest — that is where evidence has already ruled the
        thief out.
        """
        if self.severed_belief is None:
            return float(self.escape_reduction)
        return self.escape_reduction * self.severed_belief

    @property
    def total(self) -> float:
        """Higher is better. Chain progress breaks ties on equal value.

        Refused candidates keep a number rather than becoming incomparable, so
        the log can show how good the placement we turned down would have been.
        """
        penalty = 0 if self.permitted else SELF_PENALTY
        return self.value + self.chain - penalty

    @property
    def veto(self) -> str:
        """Why this placement is refused, or the empty string if it is not."""
        if self.immobilises:
            return "NO-LEGAL-MOVE-AFTER"
        if self.disconnects:
            return "CUTS-SELF-OFF"
        return ""

    def __str__(self) -> str:
        refused = f" {self.veto}" if self.veto else ""
        mass = "" if self.severed_belief is None else f" belief-{self.severed_belief:.0%}"
        return (
            f"{self.at} total={self.total:g} "
            f"(escape-{self.escape_reduction}{mass} chain+{self.chain}){refused}"
        )


def score_placement(
    state: BoardState,
    at: Position,
    axes: AxisConvention,
    target: Position,
    belief: Belief | None = None,
) -> BarrierScore:
    """Score sealing ``at``, with the thief believed to be at ``target``.

    ``belief`` weights the reduction by the probability the thief is in the
    region being removed. Omitting it keeps the raw cell count, which is the
    correct reading before a belief map exists — a uniform belief would scale
    every candidate identically and change no ranking anyway.
    """
    sealed = replace(state, barriers=state.barriers | {at})
    before = reachable_area(state, target, axes)
    after = reachable_area(sealed, target, axes)
    reduction = before - after
    weight = severed_mass(state, sealed, at, axes, target, belief) if belief else None
    return BarrierScore(
        at=at,
        escape_reduction=reduction,
        chain=chain_progress(state, at, axes),
        disconnects=not still_reaches(sealed, target, axes),
        immobilises=not legal_moves(sealed, "cop", axes),
        severed_belief=weight,
    )
