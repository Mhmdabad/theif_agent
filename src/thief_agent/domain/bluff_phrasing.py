"""The words themselves: templates, compass, and the sentence they make.

Split out of :mod:`.bluff` so the phrasing sits apart from the decision about
what to point at. Nothing here knows whether the region it is describing is
where we are or where we are not — which is exactly the property that keeps a
lie from reading differently to a truth.
"""

import random

from .board import BoardState, Position
from .hints import LANDMARKS, MAX_WORDS, truncate

TEMPLATES: tuple[str, ...] = (
    "just moved {direction}, past the {landmark}",
    "heading {direction} — the {landmark} is behind me",
    "somewhere {direction} of the {landmark}",
    "you will not find me near the {landmark}",
    "took the {direction} road by the {landmark}",
)
"""Pre-written lines. Every one stays inside the word cap once filled.

Deliberately vague about distance. A template that pinned a count of steps
would be a coordinate protocol with the numbers spelled out.
"""

COMPASS: tuple[tuple[str, tuple[int, int]], ...] = (
    ("north", (-1, 0)),
    ("south", (1, 0)),
    ("east", (0, 1)),
    ("west", (0, -1)),
)
"""Only the four the parser reads back. Saying 'north-east' would be honest
and unparseable, which helps nobody."""


def nearest_landmark(cell: Position, state: BoardState) -> str:
    """The named place closest to ``cell``.

    Ties resolve by name so two peers replaying a match generate the same
    sentence. A hint that varied run to run would not survive the audit.
    """
    last = state.grid_size - 1

    def distance(named: str) -> tuple[int, str]:
        row_fraction, col_fraction = LANDMARKS[named]
        at = (round(row_fraction * last), round(col_fraction * last))
        return abs(at[0] - cell[0]) + abs(at[1] - cell[1]), named

    return min(LANDMARKS, key=distance)


def bearing(origin: Position, destination: Position) -> str:
    """The compass word describing ``destination`` relative to ``origin``.

    The larger displacement wins, so a mostly-northward move reads "north"
    rather than picking a diagonal the parser cannot read back.
    """
    drow, dcol = destination[0] - origin[0], destination[1] - origin[1]
    if drow == 0 and dcol == 0:
        return "north"
    if abs(drow) >= abs(dcol):
        return "north" if drow < 0 else "south"
    return "west" if dcol < 0 else "east"


def compose(
    about: Position,
    state: BoardState,
    seen_from: Position,
    rng: random.Random | None = None,
) -> str:
    """A hint describing ``about``, as seen from ``seen_from``.

    Pass our real cell to tell the truth and a decoy to lie — the phrasing is
    identical either way, so the sentence itself carries no tell.
    """
    picker = rng or random.Random(0)
    template = TEMPLATES[picker.randrange(len(TEMPLATES))]
    sentence = template.format(
        direction=bearing(seen_from, about),
        landmark=nearest_landmark(about, state),
    )
    return truncate(sentence, MAX_WORDS)
