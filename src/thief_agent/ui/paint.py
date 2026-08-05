"""What the window draws, expressed without a window.

:mod:`.view` decides *what is true* — which cells are ours, which are barriers,
where the belief peaks. This decides *what is drawn*: rectangles, colours,
glyphs, in coordinates. Between them there is nothing left for a Tk callback to
get wrong except handing the results to a canvas.

**The toolkit is a Protocol, and that is the whole reason this file exists.** A
GUI written directly against ``tkinter`` can only be tested by opening a window,
which needs a display CI does not have — so in practice it is not tested at all,
and the one part of the system a human looks at becomes the one part nothing
checks. Here the layout is data: a recording painter proves the heatmap really
is deeper red where the belief is higher, that the barrier cells are dark, that
``T?`` sits at ``argmax b(s)`` and nowhere else.

**Deeper red means higher probability, scaled to the belief's own peak.** The
reasoning is in :func:`~.view.shade` and worth restating because it looks like a
presentation choice: on an 8×8 board a genuinely uncertain belief puts about
0.016 on each cell, and an absolute scale renders that as black everywhere. The
heatmap would be blank in the mid-game, which is the only interesting moment to
photograph — and FR-7.14 makes the photograph mandatory.
"""

from typing import Protocol

from ..domain.board import Position
from .banner import Banner
from .view import BARRIER, SHADES, SUSPECTED, View, heatmap

CELL = 56
"""Pixels per board square. Large enough that a screenshot is readable."""

MARGIN = 12
BANNER_HEIGHT = 44

HEAT: tuple[str, ...] = ("#111318", "#3b1d22", "#6d2429", "#a72a2c", "#e03131")
"""Five bands, dark to red. Index 0 is *no* belief, not merely low belief."""

BARRIER_FILL = "#05070a"
"""Darker than the coldest heat band: a barrier is not a cell with no belief."""

GRID_LINE = "#2b303b"
OURS = "#4dabf7"
SUSPECT = "#ffd43b"
TEXT = "#f8f9fa"


class Painter(Protocol):
    """The slice of a canvas this module needs. Two calls, no state."""

    def rectangle(self, x0: int, y0: int, x1: int, y1: int, fill: str, outline: str) -> None: ...
    def text(self, x: int, y: int, body: str, fill: str) -> None: ...


def board_size(grid: int) -> tuple[int, int]:
    """Pixel size of a window for a ``grid``×``grid`` board."""
    side = grid * CELL + 2 * MARGIN
    return side, side + BANNER_HEIGHT


def cell_box(cell: Position) -> tuple[int, int, int, int]:
    """Where one board square lands on the canvas.

    Row is the first coordinate and it maps to *y*, column to *x*. Getting this
    the wrong way round produces a board that is a mirror of the truth and looks
    entirely plausible — so it is here, once, rather than at every call site.
    """
    row, column = cell
    x0 = MARGIN + column * CELL
    y0 = BANNER_HEIGHT + MARGIN + row * CELL
    return x0, y0, x0 + CELL, y0 + CELL


def fill_for(view: View, cell: Position, heat: list[list[int]]) -> str:
    """The colour of one square: barrier first, then belief."""
    if view.at(cell).glyph == BARRIER:
        return BARRIER_FILL
    band = heat[cell[0]][cell[1]]
    return HEAT[min(band, SHADES - 1)]


def colour_for(glyph: str) -> str:
    """Marker colour, chosen by what the glyph *is* rather than where it sits.

    The suspect marker is the opponent's letter *with a question mark after it*
    — ``T?``, not ``?`` — because the window is saying "probably the thief",
    which is a different claim from "the thief". Matching on the mark rather
    than the whole glyph keeps that true for either role.

    Keying off the *cell* instead — "is this the suspected square?" — looks
    equivalent and is not. A uniform belief peaks on the first cell of the
    board, which at the start of a match is frequently our own; the marker for
    our position would then be drawn in the colour that means *the opponent is
    probably here*. Same pixel, opposite meaning.
    """
    return SUSPECT if glyph.endswith(SUSPECTED) else OURS


def paint_board(view: View, painter: Painter) -> None:
    """Draw every square, then the glyphs on top.

    Squares first and glyphs second, so a marker is never painted over by the
    cell beside it. Obvious once seen, invisible until somebody photographs a
    board where the thief's marker has half vanished.
    """
    heat = heatmap(view)
    for row in range(view.grid_size):
        for column in range(view.grid_size):
            cell = (row, column)
            x0, y0, x1, y1 = cell_box(cell)
            painter.rectangle(x0, y0, x1, y1, fill_for(view, cell, heat), GRID_LINE)

    for row in range(view.grid_size):
        for column in range(view.grid_size):
            cell = (row, column)
            glyph = view.at(cell).glyph
            if glyph.strip() and glyph != BARRIER:
                x0, y0, x1, y1 = cell_box(cell)
                painter.text((x0 + x1) // 2, (y0 + y1) // 2, glyph, colour_for(glyph))


def paint_banner(banner: Banner, grid: int, painter: Painter) -> None:
    """Draw the turn banner across the top, in the tone it carries."""
    width, _ = board_size(grid)
    painter.rectangle(0, 0, width, BANNER_HEIGHT, banner.tone.value, banner.tone.value)
    painter.text(width // 2, BANNER_HEIGHT // 2, banner.text, TEXT)


def paint_stamp(text: str, colour: str, grid: int, painter: Painter) -> None:
    """Draw the Replay App's verdict where nobody can miss it.

    FR-7.12 asks for a green ``Verified OK`` and a *blazing* red ``TAMPERED``.
    The stamp is the whole point of the Replay App — the graphics are incidental
    and the verdict is not — so it gets the banner strip rather than a status bar.
    """
    width, _ = board_size(grid)
    painter.rectangle(0, 0, width, BANNER_HEIGHT, colour, colour)
    painter.text(width // 2, BANNER_HEIGHT // 2, text, TEXT)
