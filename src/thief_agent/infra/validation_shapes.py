"""Compound field shapes carried by inbound messages.

Scent fields and ``[row, col]`` pairs are the two payload members that arrive
as containers rather than scalars, so both need bounding and element-by-element
type discipline before anything downstream indexes or sums them.
"""

import math
from typing import Any

from .validation_primitives import InvalidPayloadError

MAX_SCENT_CELLS = 10_000
"""Most cells an inbound scent field may name.

A bound on the message rather than on the board, because this layer does not
know the board: it is here so one payload cannot exhaust us before the layer
that *does* know the board gets to reject it on physics.
"""


def optional_scent(payload: dict[str, Any], key: str) -> dict[str, float] | None:
    """A ``{"row,col": intensity}`` field, or absent.

    Shape only. Whether the cells exist on *this* board, and whether the
    intensities are ones the agreed model can produce, are questions about the
    game rather than about the wire — they belong to
    :func:`~..domain.scent_audit.check_field`, which knows the board size and
    the locked emission model. Splitting them keeps one validator per question
    instead of two that can disagree.

    What is refused here is what would be dangerous before anybody looks at the
    physics: a value that is not a number, a ``NaN`` that compares unequal to
    itself and would poison every sum downstream, an infinity that would
    dominate any normalisation, a negative intensity the rulebook's clamp makes
    meaningless, and a field too large to be about a board at all.

    Booleans are rejected explicitly: ``isinstance(True, int)`` is true in
    Python, so ``true`` would otherwise be absorbed as an intensity of one.
    """
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InvalidPayloadError(f"{key!r} must be an object, got {type(value).__name__}")
    if len(value) > MAX_SCENT_CELLS:
        raise InvalidPayloadError(f"{key!r} names {len(value)} cells, over {MAX_SCENT_CELLS}")
    field: dict[str, float] = {}
    for cell, intensity in value.items():
        if not isinstance(cell, str):
            raise InvalidPayloadError(f"{key!r} keys must be strings, got {type(cell).__name__}")
        if isinstance(intensity, bool) or not isinstance(intensity, int | float):
            raise InvalidPayloadError(
                f"{key!r} intensity at {cell!r} must be a number, got {type(intensity).__name__}"
            )
        if not math.isfinite(intensity):
            raise InvalidPayloadError(f"{key!r} intensity at {cell!r} must be finite")
        if intensity < 0.0:
            raise InvalidPayloadError(f"{key!r} intensity at {cell!r} must not be negative")
        field[cell] = float(intensity)
    return field


def optional_cell(payload: dict[str, Any], key: str) -> list[int] | None:
    """A ``[row, col]`` pair, or absent.

    Here rather than in :mod:`.protocol` because two message families now parse
    cells — turns and reveals — and a parser private to one of them would have
    been copied into the other.

    Accepts a list because that is what JSON carries; rejects anything that is
    not exactly two integers, since a malformed cell would otherwise be indexed.
    """
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise InvalidPayloadError(f"{key!r} must be a [row, col] pair, got {value!r}")
    for element in value:
        if isinstance(element, bool) or not isinstance(element, int):
            raise InvalidPayloadError(f"{key!r} coordinates must be integers, got {value!r}")
    return [int(value[0]), int(value[1])]
