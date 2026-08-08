"""What we meant, as a value that exists before the sentence does.

Split out of :mod:`.bluff` because the ordering is the point: the intent is a
committed input to composition, not a label applied to its output.
"""

from dataclasses import dataclass

from .board import Position

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
