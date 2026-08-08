"""The three words the Replay App is allowed to say about a log.

Split out of ``verdict.py`` so the vocabulary of the verdict sits apart from
the machinery that earns one: this module names the outcomes and how they are
spelled, while ``verdict.py`` holds the walk that chooses between them and the
attestation it returns. Which of the three applies, and why the third one
exists at all, is argued there.

``verdict.py`` re-exports :class:`Stamp`, so a reader who wants the whole
story still has one place to import from.
"""

from enum import Enum


class Stamp(Enum):
    """The verdict, and the colour the rulebook asks it to be shown in."""

    VERIFIED_OK = "green"
    """Every step re-derived from the log itself and matched."""

    TAMPERED = "red"
    """A step opened and did not produce its commitment. The match is void."""

    INCOMPLETE = "grey"
    """A step could not be opened. Nothing proven, and nothing cleared."""

    @property
    def text(self) -> str:
        """The words on the stamp, spelled as the rulebook spells them."""
        return {
            Stamp.VERIFIED_OK: "Verified OK",
            Stamp.TAMPERED: "TAMPERED",
            Stamp.INCOMPLETE: "INCOMPLETE",
        }[self]
