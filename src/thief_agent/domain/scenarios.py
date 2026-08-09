"""Turning a belief into the handful of boards worth searching.

:mod:`.lookahead` searches a board where both pieces are known; this decides
*which* boards those are. The belief is a distribution over every free cell,
and searching all of them would be both slow and pointless — most carry
almost no mass. Taking the heaviest few and weighting by that mass is an
expectimax whose leaves are exact minimax games, which is the standard way to
plan against a hidden opponent without pretending to know where it is.

**The worst case is priced separately, on purpose.** Averaging alone will
happily accept a line that is excellent against five likely positions and
fatal against the sixth, because the average barely moves. For the thief that
sixth position is a capture and the series is over; for the cop it is a wasted
sub-game. So the score is a blend of the mean and the minimum, and
:data:`CAUTION` is how much the worst case is worth. It is a *negotiable*
tuning choice and not an Appendix F value — nothing in the rulebook fixes it.

**Ties break on the cell, never on iteration order.** A dict's order is stable
within a run but is not something a replay should depend on, so the ranking
ends in the cell's own coordinates and two equally likely cells always order
the same way.
"""

from collections.abc import Sequence

from .board import BoardState, Position

__all__ = ["CAUTION", "SCENARIOS", "blend", "likeliest"]

SCENARIOS = 5
"""How many hypotheses to search. Negotiable, not from Appendix F.

Five covers the belief's mass in every board we measured while keeping the
search inside a fraction of the turn deadline. More hypotheses buy less than
another ply of depth does.
"""

CAUTION = 0.5
"""How much the worst case counts against the average, from 0 to 1.

At 0 the agent plans for the expected opponent and walks into the unlikely
one; at 1 it plans only for its nightmare and never takes a good line that
carries any risk at all. Half is the setting that survived head-to-head play.
"""


def likeliest(
    belief: dict[Position, float], state: BoardState, limit: int = SCENARIOS
) -> list[tuple[Position, float]]:
    """The ``limit`` most likely opponent cells, with their mass, heaviest first.

    Barriers are skipped: no piece stands on a sealed cell, so mass sitting
    there is stale and searching it wastes a hypothesis. Weights are
    renormalised over what survives, so they always sum to one and the blend
    below stays comparable between turns.
    """
    live = [
        (cell, mass)
        for cell, mass in belief.items()
        if mass > 0.0 and cell not in state.barriers and _on(cell, state.grid_size)
    ]
    if not live:
        return []
    ranked = sorted(live, key=lambda row: (-row[1], row[0]))[:limit]
    total = sum(mass for _, mass in ranked)
    if total <= 0.0:
        return []
    return [(cell, mass / total) for cell, mass in ranked]


def blend(scores: Sequence[tuple[float, float]], caution: float = CAUTION) -> float:
    """Combine ``(score, weight)`` pairs into one number.

    The mean is what usually happens; the minimum is what we cannot afford.
    An empty sequence scores zero — there is nothing to prefer between
    candidates when the belief has told us nothing.
    """
    if not scores:
        return 0.0
    mean = sum(score * weight for score, weight in scores)
    worst = min(score for score, _ in scores)
    return (1.0 - caution) * mean + caution * worst


def _on(cell: Position, grid_size: int) -> bool:
    row, col = cell
    return 0 <= row < grid_size and 0 <= col < grid_size
