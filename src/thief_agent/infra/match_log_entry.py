"""The pieces one match-log row is made of, and the verdict on a whole log.

Split out of :mod:`.match_log` for length only. The names are re-exported
from there, which is where every other module still imports them from.
"""

from dataclasses import dataclass
from typing import Any

SLOTS = ("commit", "reveal", "nonce")
"""The three things recorded per step, in the only order they may arrive.

``discussion`` is a fourth slot but not one of these: it is written alongside
the reveal rather than in sequence with it, and it is **not covered by the
commitment**. Keeping it out of ``SLOTS`` is what stops it being treated as
evidence — see :meth:`MatchLog.discuss`.
"""


class MatchLogError(ValueError):
    """Raised on any attempt to write a slot that is already written."""


@dataclass(frozen=True, slots=True)
class Completeness:
    """Whether a log can be fully re-verified, and what is absent if not."""

    missing: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing

    def __str__(self) -> str:
        if self.complete:
            return "a third party can fully re-verify this sub-game"
        return "cannot be fully re-verified without " + "; ".join(self.missing)


@dataclass
class StepEntry:
    """One step's row. Each field is write-once."""

    step: int
    commit: str | None = None
    reveal: dict[str, Any] | None = None
    nonce: str | None = None
    discussion: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "commit": self.commit,
            "reveal": self.reveal,
            "nonce": self.nonce,
            "discussion": self.discussion,
        }
