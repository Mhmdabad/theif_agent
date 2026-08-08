"""Turning belief mass into a scale a still image can be read from.

Kept beside the view model rather than inside it. :mod:`.view` answers *what is
true for this agent* — our cell, the barriers, where our belief peaks — and this
module answers *how strongly to draw it*. The two questions have different
reasons to change: the first is bound by the rule against a bird's-eye view, the
second only by what a reader can see in a screenshot.

Nothing here is given a position, only heat, so the separation cannot become a
way to smuggle the opponent's cell into the display.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .view import View


SHADES = 5
"""Bands in the heat scale. Five, because a screenshot has to be readable.

A continuous gradient looks better and communicates less: the examiner is
looking at a still image for a few seconds, and the question it must answer is
"where did this agent think the opponent was", not "what is the exact
posterior". Banding makes the peak legible at a glance.
"""


def shade(heat: float, peak: float) -> int:
    """Heat as a band from 0 (cold) to :data:`SHADES` − 1 (deepest red).

    Scaled against the **observed peak** rather than against 1.0. A belief
    spread over sixty-four cells has no value above 0.02, so an absolute scale
    would render every honest mid-game board uniformly black and the heatmap
    would look broken precisely when it is working.

    Relative scaling is the reason the rulebook's screenshot requirement can be
    met at all: what a reader needs is the *shape* of the belief, and shape is
    exactly what survives normalising by the maximum.
    """
    if peak <= 0.0:
        return 0
    band = int(round(heat / peak * (SHADES - 1)))
    return max(0, min(SHADES - 1, band))


def heatmap(view: "View") -> list[list[int]]:
    """The whole board as heat bands, row by row.

    Derived from the same :class:`Cell` values the glyphs came from, so the
    picture and the letters can never disagree about which cell is suspected.
    """
    peak = max((cell.heat for cell in view.cells), default=0.0)
    return [
        [shade(view.at((row, col)).heat, peak) for col in range(view.grid_size)]
        for row in range(view.grid_size)
    ]
