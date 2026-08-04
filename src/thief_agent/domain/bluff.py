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
from dataclasses import dataclass

from .board import BoardState, Position
from .credibility import CONTRADICTION, FRESH_TRACE
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


INTENTS = ("truth", "lie")
"""The two values the Intent flag may take.

Chosen **before** the hint is composed and committed alongside the move, so
the commit binds what we meant as well as what we did. Deciding afterwards —
writing a sentence and then labelling it — would let the label be picked to
suit whatever came out, and the whole point of committing an intent is that it
cannot be revised once the hash is sent.
"""


@dataclass(frozen=True, slots=True)
class Bluff:
    """One turn's verbal output: what we said, and what we meant by it."""

    intent: str
    text: str
    about: Position

    def __post_init__(self) -> None:
        if self.intent not in INTENTS:
            raise ValueError(f"intent must be one of {INTENTS}, got {self.intent!r}")


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


class SelfContradictionError(ValueError):
    """Raised when a hint we are about to send is refuted by our own field.

    Our scent is public, unforgeable, and already on the wire. A claim the
    opponent can disprove by reading it is not a lie that costs them anything
    — it is a free credibility donation, and it arms the very detector we use
    against them.
    """


def contradicts_our_field(bluff: Bluff, own_field: dict[Position, float], predicted: float) -> bool:
    """Whether our own emitted trail refutes what we are about to say.

    The same test the opponent will run, pointed at ourselves: is the field
    at the cells we are claiming as quiet as a false claim would leave it?
    A claim about somewhere our own scent is strong is one the trail supports
    and therefore safe; a claim about somewhere it is silent is one the
    opponent convicts on arrival.
    """
    measured = max((own_field.get(cell, 0.0) for cell in _claimed(bluff)), default=0.0)
    return predicted > 0.0 and (predicted - measured) / predicted >= CONTRADICTION


def _claimed(bluff: Bluff) -> tuple[Position, ...]:
    """The cell the hint points at, plus its neighbours — a region, as sent."""
    row, col = bluff.about
    return tuple((row + drow, col + dcol) for drow in (-1, 0, 1) for dcol in (-1, 0, 1))


def vet(bluff: Bluff, own_field: dict[Position, float], predicted: float = FRESH_TRACE) -> Bluff:
    """Return ``bluff`` unless our own field refutes it.

    Applied to lies only. A truthful claim is by construction consistent with
    where we are, and running the check on it would refuse honest hints in the
    opening turns before our trail has had time to accumulate.

    Raises:
        SelfContradictionError: if the claim is one our own trail disproves.
    """
    if bluff.intent == "truth":
        return bluff
    if contradicts_our_field(bluff, own_field, predicted):
        raise SelfContradictionError(
            f"our own field refutes {bluff.about}; the opponent would convict on arrival"
        )
    return bluff
