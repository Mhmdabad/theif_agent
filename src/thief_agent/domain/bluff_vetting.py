"""Checking a lie against our own scent before we send it.

Split out of :mod:`.bluff`. The same test the opponent will run, pointed at
ourselves, so we never spend credibility on a claim our own public trail
already disproves.
"""

from .bluff_intent import Bluff
from .board import Position
from .credibility import CONTRADICTION, FRESH_TRACE


class SelfContradictionError(ValueError):
    """Raised when a hint we are about to send is refuted by our own field.

    Our scent is public, unforgeable, and already on the wire. A claim the
    opponent can disprove by reading it is not a lie that costs them anything
    — it is a free credibility donation, and it arms the very detector we use
    against them.
    """


def contradicts_our_field(bluff: Bluff, own_field: dict[Position, float], predicted: float) -> bool:
    """Whether our own emitted trail refutes what we are about to say.

    The same test the opponent will run, pointed at ourselves: is the field
    at the cells we are claiming as quiet as a false claim would leave it?
    A claim about somewhere our own scent is strong is one the trail supports
    and therefore safe; a claim about somewhere it is silent is one the
    opponent convicts on arrival.
    """
    measured = max((own_field.get(cell, 0.0) for cell in _claimed(bluff)), default=0.0)
    return predicted > 0.0 and (predicted - measured) / predicted >= CONTRADICTION


def _claimed(bluff: Bluff) -> tuple[Position, ...]:
    """The cell the hint points at, plus its neighbours — a region, as sent."""
    row, col = bluff.about
    return tuple((row + drow, col + dcol) for drow in (-1, 0, 1) for dcol in (-1, 0, 1))


def vet(bluff: Bluff, own_field: dict[Position, float], predicted: float = FRESH_TRACE) -> Bluff:
    """Return ``bluff`` unless our own field refutes it.

    Applied to lies only. A truthful claim is by construction consistent with
    where we are, and running the check on it would refuse honest hints in the
    opening turns before our trail has had time to accumulate.

    Raises:
        SelfContradictionError: if the claim is one our own trail disproves.
    """
    if bluff.intent == "truth":
        return bluff
    if contradicts_our_field(bluff, own_field, predicted):
        raise SelfContradictionError(
            f"our own field refutes {bluff.about}; the opponent would convict on arrival"
        )
    return bluff
