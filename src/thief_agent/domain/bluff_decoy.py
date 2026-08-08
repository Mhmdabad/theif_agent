"""Choosing somewhere other than here to point at.

Split out of :mod:`.bluff`. Two strategies: the furthest corner, which is the
answer when we have laid no trail yet, and a place our own emission already
corroborates, which is the answer once we have. Both resolve ties by position
so a replay of an honest match picks the same cell and passes its own audit.
"""

import random

from .board import BoardState, Position


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


def plausible_decoy(
    truth: Position, state: BoardState, own_field: dict[Position, float]
) -> Position:
    """A cell to lie about that our own trail already supports.

    The self-consistency guard exposed a flaw in the obvious strategy: a lie
    about the furthest corner is refuted by our own emission the moment the
    opponent reads it. Every such lie is a free credibility donation.

    A *credible* lie claims somewhere we genuinely have been. Our trail
    persists for dozens of turns, so an old strong trace is a place the
    opponent's own reading corroborates — and a claim their evidence supports
    is one they cannot convict. Deception works by pointing at true history,
    not by inventing geography.

    Falls back to the furthest corner when we have laid no trail yet, which is
    the opening turns; there is nothing to be credible with, and the guard
    will refuse it. That is the correct answer — early on, we should tell the
    truth.
    """
    away = {
        cell: value
        for cell, value in own_field.items()
        if abs(cell[0] - truth[0]) + abs(cell[1] - truth[1]) >= state.grid_size // 2
    }
    if not away:
        return decoy(truth, state)
    return min(away, key=lambda cell: (-away[cell], cell))
