"""The pieces a report is made of: one sub-game, and the four links.

Both are validated at construction rather than on the way out, because
FR-7.28 makes their absence a scoring matter and a report that cannot be
built wrong does not need checking later. Split out of :mod:`.report`, whose
docstring states the rule these two exist to enforce.
"""

from dataclasses import dataclass
from typing import Any


class ReportError(ValueError):
    """Raised when a report is missing something the rulebook requires."""


@dataclass(frozen=True, slots=True)
class SubGameResult:
    """One sub-game's outcome, with the commit it was played at."""

    sub_game: int
    cop_score: int
    thief_score: int
    commit_hash: str
    steps: int = 0
    technical_loss: bool = False
    started_at: str = ""
    ended_at: str = ""
    tokens: int = 0
    """This peer's spend on this sub-game. The opponent's is theirs to report."""

    log_verified: bool = True
    tampered: bool = False
    opponent_commit_hash: str = "unknown"
    """The audit's verdict on this sub-game's log, as the reference records it.

    Defaulted to a clean audit rather than an unknown one: a sub-game that
    finished without the ceremony raising *is* verified, and the runner sets
    these explicitly when it is not.
    """

    def __post_init__(self) -> None:
        if self.sub_game < 1:
            raise ReportError(f"sub-games are numbered from 1, got {self.sub_game}")
        if not self.commit_hash:
            raise ReportError(
                f"sub-game {self.sub_game} has no commit hash; FR-7.28 requires one per "
                "sub-game, and without it nobody can say which code played the game"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sub_game": self.sub_game,
            "cop_score": self.cop_score,
            "thief_score": self.thief_score,
            "commit_hash": self.commit_hash,
            "steps": self.steps,
            "technical_loss": self.technical_loss,
        }


@dataclass(frozen=True, slots=True)
class Repositories:
    """Four links, both teams, both roles. FR-7.28 requires all of them."""

    cop_repo: str
    thief_repo: str
    opponent_cop_repo: str
    opponent_thief_repo: str

    def __post_init__(self) -> None:
        missing = [name for name, value in self.to_dict().items() if not value]
        if missing:
            raise ReportError(
                f"FR-7.28 requires four repository links and {missing} are empty; a "
                "report that cannot be traced back to the code is not a result"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "cop_repo": self.cop_repo,
            "thief_repo": self.thief_repo,
            "opponent_cop_repo": self.opponent_cop_repo,
            "opponent_thief_repo": self.opponent_thief_repo,
        }
