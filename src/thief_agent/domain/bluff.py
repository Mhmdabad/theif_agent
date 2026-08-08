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

from .bluff_decoy import decoy, plausible_decoy
from .bluff_intent import INTENTS, Bluff
from .bluff_phrasing import COMPASS, TEMPLATES, bearing, compose, nearest_landmark
from .bluff_vetting import SelfContradictionError, contradicts_our_field, vet
from .board import BoardState, Position

__all__ = [
    "COMPASS",
    "INTENTS",
    "TEMPLATES",
    "Bluff",
    "SelfContradictionError",
    "bearing",
    "compose",
    "contradicts_our_field",
    "decoy",
    "nearest_landmark",
    "plausible_decoy",
    "speak",
    "vet",
]
"""Every public name this module has always exported, re-exported unchanged."""


def speak(
    truth: Position,
    state: BoardState,
    seen_from: Position,
    intent: str = "truth",
    rng: random.Random | None = None,
    own_field: dict[Position, float] | None = None,
) -> Bluff:
    """Compose this turn's hint under a pre-chosen intent.

    ``intent`` is an argument rather than a return value: the caller decides
    whether to lie, then this produces the sentence. The order is the point —
    it is what makes the committed flag a promise rather than a description.

    Supplying ``own_field`` makes a lie *credible*: it is aimed at a place our
    own trail already supports, rather than at a corner our emission refutes.

    Raises:
        ValueError: if ``intent`` is not one of :data:`INTENTS`.
    """
    if intent not in INTENTS:
        raise ValueError(f"intent must be one of {INTENTS}, got {intent!r}")
    if intent == "truth":
        about = truth
    elif own_field:
        about = plausible_decoy(truth, state, own_field)
    else:
        about = decoy(truth, state, rng)
    return Bluff(intent=intent, text=compose(about, state, seen_from, rng), about=about)
