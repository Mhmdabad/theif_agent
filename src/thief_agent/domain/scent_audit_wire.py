"""Reading a scent field off the wire without trusting a byte of it.

The first of :mod:`.scent_audit`'s three questions — *is it well formed?* — and
the vocabulary the other two are refused in. A field that fails here never
reaches the reconstruction, because a value we could not parse is not a value
we can compare against physics.
"""

import math
import re

from .board import Position
from .scent import CENTRE_INTENSITY, PRECISION

CELL = re.compile(r"^(0|[1-9][0-9]*),(0|[1-9][0-9]*)$")
"""A wire cell key, exactly as :meth:`~.trail.Trail.snapshot` renders one.

Deliberately narrower than ``int()`` would accept. ``" 1,2"``, ``"+1,2"`` and
``"01,2"`` all parse as integers and none of them is a key we would ever emit,
so accepting them would mean two peers whose fields compare unequal while both
believe they agree — the failure the pre-series lock exists to prevent.
"""


class ScentFieldError(ValueError):
    """Raised when a scent field cannot be trusted, or cannot be re-derived.

    A ``ValueError`` rather than anything more dramatic because the caller's
    job is to turn it into a recorded audit failure. An exception escaping an
    audit would be a crash mid-match, which is a technical loss scoring zero
    for both sides — the opponent's malformed field must cost *them* the
    verdict, not both of us the game.
    """


def check_field(wire: dict[str, float], board_size: int) -> dict[Position, float]:
    """Parse a received field, refusing anything we would not want to read.

    Returns the field keyed by cell, so a caller that gets a value back has one
    it may use. Nothing is dropped silently: an opponent that sends one bad
    cell has sent a bad field, and quietly keeping the rest would let them
    steer our belief with the half we accepted.

    Raises:
        ScentFieldError: on any structural or physical impossibility.
    """
    if not isinstance(wire, dict):
        raise ScentFieldError(f"scent field must be an object, got {type(wire).__name__}")
    if len(wire) > board_size * board_size:
        raise ScentFieldError(
            f"scent field has {len(wire)} cells, more than the {board_size * board_size} "
            f"a {board_size}x{board_size} board contains"
        )
    field: dict[Position, float] = {}
    for key, value in wire.items():
        if not isinstance(key, str) or not CELL.match(key):
            raise ScentFieldError(f"cell key {key!r} is not 'row,col'")
        row, _, col = key.partition(",")
        cell = (int(row), int(col))
        if not (0 <= cell[0] < board_size and 0 <= cell[1] < board_size):
            raise ScentFieldError(f"cell {key!r} is off a {board_size}x{board_size} board")
        field[cell] = _intensity(key, value)
    return field


def _intensity(key: str, value: object) -> float:
    """One cell's value, checked against the model both peers hash-locked.

    Booleans are refused explicitly: ``isinstance(True, int)`` is true in
    Python, so ``{"1,1": true}`` would otherwise be absorbed as an intensity of
    one — brighter than any emission the model can produce.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ScentFieldError(f"intensity at {key!r} must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise ScentFieldError(f"intensity at {key!r} must be finite, got {number!r}")
    if number < 0.0:
        raise ScentFieldError(
            f"intensity at {key!r} is negative ({number!r}); the rulebook clamps at zero, "
            "because there is no such thing as evidence the opponent was *not* somewhere"
        )
    if number > CENTRE_INTENSITY:
        raise ScentFieldError(
            f"intensity at {key!r} is {number!r}, above the Appendix F centre intensity "
            f"of {CENTRE_INTENSITY}; no cell can be fresher than a fresh emission"
        )
    if number != round(number, PRECISION):
        raise ScentFieldError(
            f"intensity at {key!r} carries more precision than the wire transmits: "
            f"{number!r} is not {PRECISION} decimals"
        )
    return number
