"""Reading the opponent's words as a claim about the board.

A hint is free natural language — "I slipped past the bridge", "heading up
north". This turns that into a claim: a weight over cells, which is what the
Bayes update consumes. It does not decide anything; it only says what the
opponent asserted.

**Numeric coordinates are forbidden and are refused, not parsed.** The
rulebook bans a numeric-coordinate protocol outright, and the ban is the point
of the whole verbal layer: a hint that says "3,4" is not a claim in natural
language, it is a position exchange wearing a sentence. Accepting one would
mean playing a different game from the one both teams agreed to — and quietly
rewarding an opponent who cheats, since their "hint" would be worth more than
anyone else's. So a coordinate-bearing hint raises rather than being read
generously.

Everything else is read charitably. The opponent is not obliged to be clear,
only truthful-or-not, and an unparseable hint is silence rather than an error:
:func:`parse` returns an empty claim, the Bayes update leaves the prior alone,
and the trail still speaks. Refusing to act on a hint we did not understand is
correct; refusing to *play* because of one is not.
"""

import unicodedata

from .board import BoardState, Position
from .hints_lexicon import (
    DIRECTIONS,
    FUTURE_ACTION,
    LANDMARKS,
    MAX_WORDS,
    NUMERIC,
    policy_text,
    words,
)

__all__ = [
    "DIRECTIONS",
    "FUTURE_ACTION",
    "LANDMARKS",
    "MAX_WORDS",
    "NUMERIC",
    "CoordinateProtocolError",
    "parse",
    "policy_text",
    "truncate",
    "words",
]
"""Every public name this module has always exported, re-exported unchanged."""


class CoordinateProtocolError(ValueError):
    """Raised when a hint carries numeric coordinates.

    Not a parse failure — a rules violation by the sender. Surfaced so the
    caller can record it rather than silently treating a cheat as noise.
    """


def _spread(centre: Position, state: BoardState, weight: float) -> dict[Position, float]:
    """Weight ``centre`` and its neighbours, clipped to the board.

    A claim is a region, not a pin. "North" does not name a cell, and treating
    it as one would make an honest but vague hint look like a lie the moment
    the thief was one square off.
    """
    claim: dict[Position, float] = {}
    for drow in (-1, 0, 1):
        for dcol in (-1, 0, 1):
            cell = (centre[0] + drow, centre[1] + dcol)
            if state.in_bounds(cell):
                claim[cell] = weight if (drow, dcol) == (0, 0) else weight * 0.5
    return claim


def parse(text: str, state: BoardState, speaker: Position) -> dict[Position, float]:
    """Read ``text`` as a claim about where ``speaker`` is or has gone.

    ``speaker`` is where we currently believe them to be — a direction is
    relative to that, since "north" means north *of them*, not of the board.

    Returns an empty claim when nothing is recognised. That is silence, and
    the Bayes update treats silence as absent information rather than as
    evidence against anything.

    Raises:
        CoordinateProtocolError: if the hint carries numeric coordinates.
    """
    if NUMERIC.search(policy_text(text)):
        raise CoordinateProtocolError(f"numeric coordinates are forbidden: {text!r}")

    claim: dict[Position, float] = {}
    last = state.grid_size - 1
    for word in words(text):
        if word in DIRECTIONS:
            drow, dcol = DIRECTIONS[word]
            step = max(1, state.grid_size // 3)
            centre = (
                min(last, max(0, speaker[0] + drow * step)),
                min(last, max(0, speaker[1] + dcol * step)),
            )
            for cell, weight in _spread(centre, state, 1.0).items():
                claim[cell] = max(claim.get(cell, 0.0), weight)
        elif word in LANDMARKS:
            row_fraction, col_fraction = LANDMARKS[word]
            centre = (round(row_fraction * last), round(col_fraction * last))
            for cell, weight in _spread(centre, state, 1.0).items():
                claim[cell] = max(claim.get(cell, 0.0), weight)
    return claim


def truncate(text: str, cap: int = MAX_WORDS) -> str:
    """Cut our own hint to the agreed word cap, and make it wire-legal.

    Applied to what we send, never to what we receive. Emitting a hint over
    the cap is our violation to avoid; receiving one is the opponent's, and
    discarding it would let them silence us by rambling.

    **Always rejoined, never returned as given.** Returning a short hint
    untouched preserved whatever the source put in it, and a language model
    answering in two lines put a newline there — category ``Cc``, which
    :mod:`~..infra.validation` refuses, which aborts the match rather than the
    turn. Templates never contained one, so nothing found this until a real
    provider was configured. Splitting on whitespace already folds newlines and
    tabs; the filter below covers the control characters that are not
    whitespace and so would survive a split.
    """
    tokens = "".join(" " if unicodedata.category(c) == "Cc" else c for c in text).split()
    return " ".join(tokens[:cap])
