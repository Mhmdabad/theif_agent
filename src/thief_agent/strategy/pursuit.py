"""Turning a caught lie into a heading.

The rulebook's worked example (PDF p. 47) ends with three actions, and this
module is the third: the cop lowers the trust it assigns to verbal claims,
re-weights its probability matrix toward the real scent mass, and **re-aims
pursuit — not toward the declared direction, but toward the true source**.

That last distinction is the whole point and it is easy to get wrong. A lie
tells us the claim is false. It does **not** tell us the opposite is true: a
thief who says "north" while sitting in the south-east could equally have been
somewhere else entirely. Chasing the negation of a lie is still letting the
liar choose our heading. The trail already knows the answer, so we ask it.

The order matters too, and it is not the order the sentence is written in.
Credibility is updated **before** the hint is folded into the belief, so the
lie is weighed at its newly reduced trust rather than at the trust it enjoyed
before it was caught. Applying the hint first and lowering trust afterwards
would let every lie land once at full strength — the opponent would simply
alternate, paying one turn of credibility for one turn of misdirection.

This is the asymmetry that makes the manipulation double-edged: the attempt to
mislead is what exposes the position, because the trail cannot be forged and
the claim can.
"""

import logging

from ..domain.belief import Belief
from ..domain.board import Position
from ..domain.credibility import Credibility, Verdict, check, true_source
from ..domain.inference import update

logger = logging.getLogger(__name__)


def observe(
    belief: Belief,
    credibility: Credibility,
    field: dict[Position, float],
    claim: dict[Position, float] | None = None,
) -> Verdict | None:
    """Fold one turn's evidence in, checking any claim against the trail first.

    Returns the verdict on the claim, or ``None`` when the opponent said
    nothing. A silent turn still updates belief — the trail speaks whether or
    not the thief does.
    """
    verdict = check(claim, field) if claim else None
    if verdict is not None:
        credibility.observe(verdict)
        logger.info("hint %s -> %s", verdict, credibility)
    update(belief, field, claim=claim, reliability=credibility.reliability)
    return verdict


def target(belief: Belief, field: dict[Position, float]) -> Position | None:
    """Where to pursue: the belief peak, or the trail when belief is silent.

    Belief is preferred because it has already combined both sources. The
    trail is the fallback for the opening turns, before any evidence has
    concentrated the distribution — pursuing the uniform prior's argmax would
    send the cop to cell (0, 0) regardless of where the thief is.
    """
    if belief.concentration() > 0.0:
        return belief.most_likely()
    return true_source(field)


def reaim(
    belief: Belief,
    credibility: Credibility,
    field: dict[Position, float],
    claim: dict[Position, float] | None = None,
) -> tuple[Position | None, Verdict | None]:
    """One full observation, returning the cell to pursue and the verdict.

    The single call the brain makes each turn. After a contradicted claim the
    returned target follows the scent mass, because the discredited hint has
    been down-weighted before it ever reached the belief.
    """
    verdict = observe(belief, credibility, field, claim)
    aim = target(belief, field)
    if verdict is not None and verdict.contradicted:
        logger.info("lie detected; re-aiming at %s rather than the claim", aim)
    return aim, verdict
