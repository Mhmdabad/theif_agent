"""Combining two disagreeing witnesses: the trail and the opponent's words.

The whole difficulty of this game is that the two evidence sources are not
equally trustworthy and cannot be averaged.

**Scent is physics.** It is emitted by movement itself, cannot be suppressed,
cannot be forged, and cannot be emitted somewhere the agent is not. It is
noisy — decay makes an old strong trace look like a fresh weak one — but it
never lies.

**A hint is a claim.** It may be true, it may be a deliberate lie, and the
rules permit both. So it enters the update weighted by a *reliability*
coefficient, and that weight is earned rather than assumed.

Both arrive as likelihoods over cells and multiply into the belief, which is
what makes the disagreement resolve numerically instead of by a rule about
which source wins. When they agree the posterior sharpens; when they conflict
the stronger evidence moves it and the weaker one merely slows it down.

Reliability is applied by **flattening, not by discounting**. A hint at
reliability r is mixed toward the uniform distribution — ``r * claim +
(1 - r) * flat`` — so at r = 0 it contributes exactly nothing and at r = 1 it
is taken at face value. Scaling the claim by r instead would be a mistake that
looks identical: the belief renormalises, so a uniformly scaled likelihood has
no effect at all, and an unreliable hint would be indistinguishable from a
perfectly reliable one.
"""

from .belief import Belief
from .board import Position

MAX_RELIABILITY = 0.95
"""Ceiling on how far a verbal claim is ever trusted.

Not 1.0, and the reason is structural rather than cautious: the rules
*permit* the opponent to lie, so certainty in their word is never justified
by anything. At exactly 1.0 the flattening term vanishes and a single hint
annihilates every cell it does not name — including cells the trail actively
supports — and no later evidence can revive them. A ceiling keeps the
opponent's speech influential and non-final, which is the only correct
standing for an adversary's testimony.
"""

FLOOR = 0.05
"""Smallest likelihood any cell receives from scent evidence.

Zero would make a single quiet turn permanently disprove a cell, and the
opponent controls where it emits. A floor keeps every cell recoverable, which
matters because the thief's whole strategy is to be somewhere the cop is not
looking.
"""


def scent_likelihood(
    field: dict[Position, float], cells: list[Position], floor: float = FLOOR
) -> dict[Position, float]:
    """Evidence from the opponent's sampled trail.

    Intensity is read as recency, so a strong cell is more likely to be where
    the opponent is *now*. Cells the field does not mention get ``floor``
    rather than zero: silence is absent information, and a cell the opponent
    simply has not walked through recently must stay reachable by later
    evidence.
    """
    return {cell: max(floor, field.get(cell, 0.0)) for cell in cells}


def hint_likelihood(
    claim: dict[Position, float], cells: list[Position], reliability: float
) -> dict[Position, float]:
    """Evidence from a verbal claim, flattened toward uniform by reliability.

    At ``reliability = 0`` every cell gets the same value, so the hint cannot
    move the belief at all. It is capped at :data:`MAX_RELIABILITY` rather
    than 1, because a claim from someone the rules allow to lie should never
    become unanswerable.

    Flattening rather than scaling is the load-bearing choice. The belief
    renormalises after every update, so multiplying a claim by a constant
    changes nothing — an implementation that "discounted" an unreliable hint
    that way would apply it at full strength while appearing to weigh it.
    """
    weight = min(MAX_RELIABILITY, max(0.0, reliability))
    if not cells:
        return {}
    flat = 1.0 / len(cells)
    return {cell: weight * claim.get(cell, 0.0) + (1.0 - weight) * flat for cell in cells}


def update(
    belief: Belief,
    field: dict[Position, float],
    claim: dict[Position, float] | None = None,
    reliability: float = 0.5,
) -> None:
    """One full observation: scent first, then the hint if there was one.

    Scent is applied unconditionally because it is emitted whether or not the
    opponent chose to speak. The hint is optional, and a turn with no hint is
    a turn where only physics spoke.
    """
    cells = list(belief.mass)
    belief.update(scent_likelihood(field, cells))
    if claim:
        belief.update(hint_likelihood(claim, cells, reliability))
