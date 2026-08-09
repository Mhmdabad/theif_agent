"""One sub-game's verdict: what was played, and what the audit made of it.

Split from :mod:`.match` unchanged. It lives apart from the runner because an
outcome outlives the series that produced it: the report is assembled from
these, and one can be rebuilt from files with no runner anywhere.
"""

from dataclasses import dataclass

from ..domain.scoring import Outcome, scores_for
from ..infra.ceremony import AuditResult
from ..infra.match_log import MatchLog
from .subgame import Played, SubGame

__all__ = ["SubGameOutcome"]


@dataclass(frozen=True, slots=True)
class SubGameOutcome:
    """One sub-game, and what we concluded about the other side's play."""

    number: int
    played: Played
    audit: AuditResult
    log: MatchLog
    game: "SubGame | None" = None
    """The sub-game that produced this, for anything wanting its ceremony.

    Optional because an outcome can be reconstructed from files without one.
    """

    @property
    def clean(self) -> bool:
        return self.audit.clean

    @property
    def outcome(self) -> Outcome:
        """How this sub-game finished, in the rulebook's vocabulary."""
        return Outcome.CAPTURE if self.played.captured else Outcome.SURVIVAL

    def scores(self) -> tuple[int, int]:
        """``(cop, thief)`` for this sub-game, from the Appendix F table."""
        return scores_for(self.outcome)
