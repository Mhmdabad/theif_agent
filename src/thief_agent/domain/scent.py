"""Scent emission: the signal an agent cannot help leaving.

Every agent emits on every turn — moving or standing still — a field centred
on its own cell. This is the stigmergic channel: neither side can suppress it,
forge it, or emit somewhere it is not, which is what makes it the evidence a
verbal claim gets checked against. A hint can lie; a trail cannot.

**The falloff is a Euclidean hill, and the rulebook proves it in a figure.**
Figure 4 (PDF p. 44) prints the whole 5x5 field, and two of its numbers settle
the shape on their own: ``(1,2)`` and ``(2,1)`` are 0.14 while ``(2,2)`` is
0.04. Under Chebyshev distance all three are ring 2 and would be equal. They
are not, so intensity falls with ``dr**2 + dc**2``.

That difference is the mechanism, not a detail. Ch. 4.3 explains the point of
spreading at all: a single hot cell is a crude measure, while a hill marks
*direction* even when the exact cell is missed. A square terrace of equal
border values carries no direction, so flattening the falloff removes the
reason the field is emitted.

The reference implementation uses Chebyshev, and it is therefore selectable —
:data:`CHEBYSHEV` — but not the default. The emission model is exchanged and
**hash-locked before a series** precisely because implementations differ; that
lock is the resolution procedure, so the honest posture is to default to the
authoritative source and be able to agree the other.

Three properties are load-bearing for that agreement and each looks cosmetic:

* **Rounding to three decimals at emission.** Floats do not reproduce across
  implementations; a rounded field does. This is what makes "same formula"
  mean "same numbers".
* **Clipping to the board, not wrapping.** A field emitted in a corner is
  simply smaller, and the centre keeps full intensity.
* **No barrier awareness.** Scent passes through walls. Barriers block
  movement, not diffusion, and a plausible-sounding occlusion rule invented
  here would break the lock without anyone noticing until audit.
"""

from ..shared.appendix_f import book_value
from .board import Position
from .scent_falloff import (
    CHEBYSHEV,
    DEFAULT_FALLOFF,
    GAUSSIAN,
    MODELS,
    SIGMA,
    Falloff,
    chebyshev,
    gaussian,
)

__all__ = [
    "CENTRE_INTENSITY",
    "CHEBYSHEV",
    "DEFAULT_FALLOFF",
    "GAUSSIAN",
    "GRID_SIZE",
    "MODELS",
    "PRECISION",
    "SIGMA",
    "Falloff",
    "chebyshev",
    "emission",
    "gaussian",
    "numeric_example",
]

PRECISION = 3
"""Decimal places every intensity is rounded to.

Not cosmetic. Two peers running the same formula in different float orders
disagree in the last bits, and the disagreement is permanent because the field
is hashed into the pre-series lock.
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


def emission(
    centre: Position,
    board_size: int,
    intensity: float = CENTRE_INTENSITY,
    grid_size: int = GRID_SIZE,
    falloff: Falloff = DEFAULT_FALLOFF,
) -> dict[Position, float]:
    """The field laid down by an agent standing on ``centre``.

    Clipped to the board, so a corner emission is a quarter of a full one.
    Cells that fall to zero are still returned: an explicit zero and an absent
    key mean different things once fields are merged, and collapsing them here
    would make the wire form depend on where the emitter happened to stand.
    """
    half = grid_size // 2
    field: dict[Position, float] = {}
    for offset_row in range(-half, half + 1):
        for offset_col in range(-half, half + 1):
            cell = (centre[0] + offset_row, centre[1] + offset_col)
            if 0 <= cell[0] < board_size and 0 <= cell[1] < board_size:
                value = falloff(offset_row, offset_col, intensity, grid_size)
                field[cell] = round(max(0.0, value), PRECISION)
    return field


def numeric_example(
    intensity: float = CENTRE_INTENSITY,
    grid_size: int = GRID_SIZE,
    falloff: Falloff = DEFAULT_FALLOFF,
) -> str:
    """The worked example exchanged at the pre-series lock.

    The rulebook requires both teams to swap the emission model *with a
    concrete numeric example* and hash the agreement. A formula agreed in prose
    is a formula two teams can implement differently; a formula agreed
    alongside the numbers it produces is not.

    Reports whichever model is in force, so a negotiated Chebyshev series
    exchanges Chebyshev numbers rather than the ones we prefer.
    """
    name = next((key for key, model in MODELS.items() if model is falloff), "custom")
    half = grid_size // 2
    rows = []
    for offset_row in range(-half, half + 1):
        rows.append(
            " ".join(
                f"{round(max(0.0, falloff(offset_row, offset_col, intensity, grid_size)), 2):.2f}"
                for offset_col in range(-half, half + 1)
            )
        )
    return f"{name} {grid_size}x{grid_size}, centre tau={intensity}:\n" + "\n".join(rows)
