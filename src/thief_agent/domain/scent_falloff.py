"""Falloff models: the shape of the hill an emission lays down.

Split out of :mod:`.scent`, which keeps the board-facing emission itself. A
falloff here is a pure function of an offset from the centre cell; it knows
nothing about the board, the clipping to it, or the rounding applied on the
way out. The constants below are part of the pre-series hash lock exactly as
they were when they lived next to the emission.
"""

import math
from collections.abc import Callable

SIGMA = 1.15
"""Spread of the Gaussian, fitted to figure 4 rather than chosen.

The figure prints the field to two decimals; ``0.9 * exp(-(dr**2+dc**2) /
(2*sigma**2))`` reproduces every printed value for sigma in [1.148, 1.1544],
and 1.15 is the round number inside that interval. It is derived from the
rulebook, not tuned for play, because it is an agreement term rather than a
strategy parameter.
"""

Falloff = Callable[[int, int, float, int], float]
"""A falloff model: ``(dr, dc, centre_intensity, grid_size) -> intensity``."""


def gaussian(offset_row: int, offset_col: int, intensity: float, grid_size: int) -> float:
    """The rulebook's radial hill. Figure 4, PDF p. 44.

    ``grid_size`` is unused: the hill's shape is set by :data:`SIGMA`, and the
    grid only decides where it is cut off. Kept in the signature so every
    falloff model is interchangeable.
    """
    del grid_size
    squared = offset_row * offset_row + offset_col * offset_col
    return intensity * math.exp(-squared / (2 * SIGMA * SIGMA))


def chebyshev(offset_row: int, offset_col: int, intensity: float, grid_size: int) -> float:
    """The reference implementation's square terrace.

    Selectable so it can be agreed at negotiation against an opponent running
    the reference code, which is a likely enough case to be worth supporting
    without a code change. Rings are 0.9, 0.6, 0.3.
    """
    step = intensity / (grid_size // 2 + 1)
    return intensity - step * max(abs(offset_row), abs(offset_col))


CHEBYSHEV: Falloff = chebyshev
GAUSSIAN: Falloff = gaussian
DEFAULT_FALLOFF: Falloff = gaussian
"""The rulebook's model, used unless a series is negotiated otherwise."""

MODELS: dict[str, Falloff] = {"gaussian": gaussian, "chebyshev": chebyshev}
"""Named models, so a negotiated agreement can name one on the wire."""
