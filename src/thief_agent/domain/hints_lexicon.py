"""The words a hint is read against, and the shapes it may not take.

The vocabulary half of :mod:`.hints`: the two patterns that decide whether a
hint is a rules violation, the compass and landmark tables a claim is read
against, and the two text helpers that normalise a hint before either is
applied. Separated so the tables can be read — and disagreed with — without
the parsing logic in the way; they are a negotiable default, not a mechanism.
"""

import re
import unicodedata

MAX_WORDS = 15
"""Appendix F word cap. Longer hints are truncated, not rejected.

The cap is on what *we* emit. A long hint from the opponent is their protocol
problem, and dropping it would hand them a way to make us ignore them.
"""

NUMERIC = re.compile(
    r"\b\d+\s*(?:[,;]|\band\b)\s*\d+\b"
    r"|\b(?:row|col(?:umn)?|cell|square)\s*(?:=|:|is|number|no\.?)*\s*\d+\b"
    r"|\b[xy]\s*=\s*\d+\b(?:\s*[,;]?\s*|\s+and\s+)"
    r"[xy]\s*=\s*\d+\b"
    r"|\(\s*\d+\s*[,;]\s*\d+\s*\)",
    re.IGNORECASE,
)
"""Shapes that constitute a coordinate protocol rather than a hint."""

FUTURE_ACTION = re.compile(
    r"(?:\b(?:next|future)\s+(?:turn|move)\b[^.!?]*\b(?:move|go|head|travel|stay|"
    r"wait|place|build|north|south|east|west|up|down|left|right|barrier)\b)"
    r"|(?:\b(?:i|we)\s+(?:will|shall|am\s+going\s+to|intend\s+to|plan\s+to|"
    r"(?:'ll))\s+(?:move|go|head|travel|stay|wait|place|build|"
    r"north|south|east|west|up|down|left|right|barrier)\b)"
    r"|(?:\b(?:i|we)'ll\s+(?:move|go|head|travel|stay|wait|place|build|"
    r"north|south|east|west|up|down|left|right|barrier)\b)",
    re.IGNORECASE,
)
"""Explicit disclosures of a not-yet-committed action."""

DIRECTIONS: dict[str, tuple[int, int]] = {
    "north": (-1, 0),
    "up": (-1, 0),
    "south": (1, 0),
    "down": (1, 0),
    "east": (0, 1),
    "right": (0, 1),
    "west": (0, -1),
    "left": (0, -1),
}
"""Compass and colloquial synonyms. The thief will not always say 'north'."""

LANDMARKS: dict[str, tuple[float, float]] = {
    "harbour": (1.0, 0.5),
    "harbor": (1.0, 0.5),
    "bridge": (0.5, 0.0),
    "downtown": (1.0, 1.0),
    "uptown": (0.0, 0.5),
    "park": (0.5, 0.5),
    "centre": (0.5, 0.5),
    "center": (0.5, 0.5),
    "midtown": (0.5, 0.5),
    "docks": (1.0, 0.0),
    "airport": (0.0, 1.0),
}
"""Map-area landmarks as fractions of the board, so they scale with grid size.

Named places rather than coordinates: that is the whole point of the verbal
channel. The set is a default for the book's "New York" and is negotiable —
both sides only need to agree which words mean roughly where.
"""


def policy_text(text: str) -> str:
    """Canonical text used only for policy matching; the hint itself stays verbatim."""
    return unicodedata.normalize("NFKC", text).casefold().replace("’", "'").replace("‘", "'")


def words(text: str) -> list[str]:
    """Lowercased word tokens, punctuation stripped."""
    return re.findall(r"[a-z]+", text.lower())
