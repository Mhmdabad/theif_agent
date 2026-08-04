"""What the live display is allowed to know, computed before anything is drawn.

The rulebook's constraint on the GUI is not cosmetic: an agent shows **its own
local truth** and never a bird's-eye view of the board. The reason is the whole
premise of the project — this is a Dec-POMDP, each side acts under partial
observation, and a window that happened to render the opponent's real cell
would make the belief map decorative and the hints pointless. It would also be
invisible in a screenshot, because a correct-looking board and a cheating board
differ by one variable.

So the view model is built here, in a function that **cannot see the
opponent's position** — not because it chooses not to look, but because the
argument is not passed. :func:`render` takes our own cell, our belief and the
barriers. There is no parameter that could carry the truth, which is the only
version of this rule that survives someone later "just adding a debug marker".

Separating the model from the widget is what makes that checkable. A Tkinter
canvas cannot be asserted on in CI, and a rule this important should not be
tested by looking at a screenshot.
"""

from dataclasses import dataclass
from typing import Any

from ..domain.actions import ROLES
from ..domain.belief import Belief
from ..domain.board import BoardState, Position

SUSPECTED = "?"
"""Marks the belief peak. A question mark because that is what it is."""

BARRIER = "#"
EMPTY = " "


@dataclass(frozen=True, slots=True)
class Cell:
    """One square, as the display should draw it."""

    row: int
    col: int
    glyph: str
    heat: float
    """Belief mass, 0.0–1.0. The heatmap's only input."""

    def to_dict(self) -> dict[str, Any]:
        return {"row": self.row, "col": self.col, "glyph": self.glyph, "heat": self.heat}


@dataclass(frozen=True, slots=True)
class View:
    """Everything the window may draw, and nothing else."""

    role: str
    cells: tuple[Cell, ...]
    grid_size: int
    suspected: Position | None
    step: int

    def at(self, cell: Position) -> Cell:
        return self.cells[cell[0] * self.grid_size + cell[1]]

    def glyphs(self) -> list[str]:
        """One string per row. The test-readable form, and a usable fallback."""
        return [
            "".join(self.at((row, col)).glyph for col in range(self.grid_size))
            for row in range(self.grid_size)
        ]


def render(
    state: BoardState,
    belief: Belief,
    role: str,
    ours: Position,
    our_glyph: str,
    opponent_glyph: str,
) -> View:
    """Build the view from our own cell, our belief, and the board's barriers.

    **There is no argument for the opponent's true position.** That is the
    point: the rule against a bird's-eye view cannot be enforced by discipline
    inside a drawing routine, only by never handing it the value.

    ``ours`` is passed explicitly rather than read off ``state`` by role, so a
    caller cannot accidentally hand this the opponent's cell by flipping one
    character — it has to be the position the caller already knows is its own.

    Both glyphs are parameters so this file is byte-identical in the two
    repositories. A module that hard-coded ``"C"`` here and ``"T"`` there would
    be a shared module that has quietly stopped being shared, which is the
    failure the drift check exists to catch.
    """
    if role not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}, got {role!r}")
    peak = belief.most_likely()
    cells = []
    for row in range(state.grid_size):
        for col in range(state.grid_size):
            here = (row, col)
            if here == ours:
                glyph = our_glyph
            elif state.is_barrier(here):
                glyph = BARRIER
            elif here == peak:
                glyph = opponent_glyph + SUSPECTED
            else:
                glyph = EMPTY
            cells.append(Cell(row=row, col=col, glyph=glyph, heat=belief.at(here)))
    return View(
        role=role,
        cells=tuple(cells),
        grid_size=state.grid_size,
        suspected=peak,
        step=state.step,
    )
