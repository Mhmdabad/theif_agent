"""Saying where we are, or where we are not.

The output half of the verbal channel. :mod:`.hints` reads the opponent's
words; this writes ours — a short sentence naming a direction or a landmark,
never a coordinate.

**Templates, not a model.** The rulebook makes `template` the default provider
and calls it the recommended route, because the verbal layer is worth few
marks and the movement algorithm is worth many. Pre-written lines cost zero
tokens, cannot time out inside a thirty-second turn, and replay identically —
which matters, because a hint that differs between a match and its replay is a
hint the audit cannot check.

**We describe a region, never a cell.** Naming a square would be a coordinate
protocol in prose, which the rulebook forbids. Saying "north of the park" is
both legal and, usefully, imprecise: it is true across several cells, so an
honest hint stays honest when we move.

A lie is generated the same way as a truth — the same phrasing over a
different region. Hints that read differently when we are lying would be a
tell worth more to the opponent than the lie costs them.
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


def decoy(truth: Position, state: BoardState, rng: random.Random | None = None) -> Position:
    """A cell to lie about: the corner furthest from where we actually are.

    Far rather than merely different, because a lie one square off is a lie
    the *trail confirms* — the opponent's scent reading would support it and
    we would have spent credibility to tell them something true.

    Corners rather than the mirrored cell, which was the first version and was
    wrong: mirroring a centre cell lands two squares away. On a 7x7 board
    (2, 3) mirrors to (4, 3), close enough that our own emission reaches it.
    The furthest corner is always at least ``grid_size - 1`` away.

    Ties resolve by position so a replay tells the same lie.
    """
    del rng
    last = state.grid_size - 1
    corners = ((0, 0), (0, last), (last, 0), (last, last))
    return max(corners, key=lambda c: (abs(c[0] - truth[0]) + abs(c[1] - truth[1]), -c[0], -c[1]))
