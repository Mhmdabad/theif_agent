"""Scent emission: the signal an agent cannot help leaving.

Every agent emits on every turn — moving or standing still — a square field
centred on its own cell. This is the stigmergic channel: neither side can
suppress it, forge it, or emit somewhere it is not, which is what makes it the
evidence a verbal claim gets checked against. A hint can lie; a trail cannot.

**Chebyshev falloff, not Euclidean.** Intensity drops by a fixed step per ring,
where a ring is ``max(|dr|, |dc|)`` — so the field is a square terrace, and
every cell on the border of the 5x5 carries the same value. The rulebook calls
the emission *radial*, and so does the reference implementation, in the same
sentence in which it uses Chebyshev distance: "radial" means emanating from a
centre, not measured with a circle.

Matching the reference here is not deference, it is the acceptance criterion.
The emission model is exchanged and **hash-locked before a series**, so a field
that differs from the opponent's is not a weaker strategy — it is a failed
negotiation at best and a disputed match at worst.

Three properties are load-bearing for that agreement and each looks like a
detail:

* **Rounding to three decimals at emission.** Floats do not reproduce across
  implementations; a rounded field does. This is what makes "same formula"
  mean "same numbers".
* **Clipping to the board, not wrapping.** A field emitted in a corner is
  simply smaller.
* **No barrier awareness.** Scent passes through walls. Barriers block
  movement, not diffusion, and adding a plausible-sounding occlusion rule
  would silently break the lock.
"""

from ..shared.appendix_f import book_value
from .board import Position

PRECISION = 3
"""Decimal places every intensity is rounded to.

Not cosmetic. Two peers running the same formula in different float orders
disagree in the last bits, and the disagreement is permanent because the
field is hashed into the pre-series lock.
"""


def _fixed_float(section: str, key: str) -> float:
    value = book_value(section, key)
    if not isinstance(value, int | float):
        raise TypeError(f"{section}.{key} is {type(value).__name__}, not a number")
    return float(value)


CENTRE_INTENSITY: float = _fixed_float("pheromones", "pheromone_center_intensity")
"""Appendix F centre intensity. *Fixed* - deviating disqualifies the team."""

GRID_SIZE: int = int(_fixed_float("pheromones", "pheromone_grid_size"))
"""Appendix F emission width. *Fixed*. Odd, so the emitter has a centre cell."""


def ring(offset_row: int, offset_col: int) -> int:
    """Chebyshev distance from the emission centre.

    The number of rings out, where every cell of a ring shares one intensity.
    """
    return max(abs(offset_row), abs(offset_col))


def falloff(intensity: float, grid_size: int = GRID_SIZE) -> float:
    """Intensity lost per ring.

    ``intensity / (half + 1)`` rather than ``intensity / half``, so the
    outermost ring still carries signal instead of decaying to nothing. With
    the book's 5x5 at 0.9 the rings are 0.9, 0.6, 0.3 — a field whose edge is
    still worth reading, which is the point of emitting a field at all.
    """
    return intensity / (grid_size // 2 + 1)


def emission(
    centre: Position,
    board_size: int,
    intensity: float = CENTRE_INTENSITY,
    grid_size: int = GRID_SIZE,
) -> dict[Position, float]:
    """The field laid down by an agent standing on ``centre``.

    Clipped to the board, so a corner emission is a quarter of a full one.
    Cells that fall to zero are still returned: an explicit zero and an absent
    key mean different things once fields are merged, and collapsing them here
    would make the wire form depend on where the emitter happened to stand.
    """
    half = grid_size // 2
    step = falloff(intensity, grid_size)
    field: dict[Position, float] = {}
    for offset_row in range(-half, half + 1):
        for offset_col in range(-half, half + 1):
            cell = (centre[0] + offset_row, centre[1] + offset_col)
            if 0 <= cell[0] < board_size and 0 <= cell[1] < board_size:
                value = intensity - step * ring(offset_row, offset_col)
                field[cell] = round(max(0.0, value), PRECISION)
    return field


def numeric_example(intensity: float = CENTRE_INTENSITY, grid_size: int = GRID_SIZE) -> str:
    """The worked example exchanged at the pre-series lock.

    The rulebook requires both teams to swap the emission model *with a
    concrete numeric example* and hash the agreement. A formula agreed in
    prose is a formula two teams can implement differently; a formula agreed
    alongside the numbers it produces is not.
    """
    step = falloff(intensity, grid_size)
    rings = ", ".join(
        f"ring {distance} = {round(max(0.0, intensity - step * distance), PRECISION)}"
        for distance in range(grid_size // 2 + 1)
    )
    return (
        f"emission {grid_size}x{grid_size} centred at tau={intensity}, "
        f"Chebyshev falloff {round(step, PRECISION)} per ring: {rings}"
    )
