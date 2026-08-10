"""Who plays which role in which sub-game, and what a whole series adds up to.

The rulebook scores a match per **group pair**, accumulated over every sub-game
between the two groups: the tie rule (p. 87) compares the two groups' series
totals, and a group's total is only fair if it played both roles on the way to
it. The schedule that makes it fair is the cohort's — **natural role on odd
sub-games, the opposite on even ones** (reference ``sdk/series.py``) — so two
peers that agree who opens as police have agreed the whole schedule without
another message.

The arithmetic mirrors the reference's ``aggregate`` deliberately, down to the
tie rule adding the Appendix F tie score *on top of* the equal totals: rule 35
requires both sides to publish byte-identical results, and the cheapest way to
agree with the cohort is to compute exactly what it computes.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from .actions import ROLES

__all__ = ["SeriesStanding", "opposite", "role_for", "tally"]


def opposite(role: str) -> str:
    """The other side of the board."""
    _require(role)
    return "thief" if role == "police" else "police"


def role_for(natural: str, sub_game: int) -> str:
    """Natural role on odd sub-games, the opposite on even ones.

    ``natural`` is the role played in sub-game 1 — agreed with the opponent,
    who starts from the opposite one, so the two schedules interlock.
    """
    _require(natural)
    if sub_game < 1:
        raise ValueError(f"sub-games are numbered from 1, got {sub_game}")
    return natural if sub_game % 2 == 1 else opposite(natural)


def _require(role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}, got {role!r}")


@dataclass(frozen=True, slots=True)
class SeriesStanding:
    """A whole series, summed the way the book scores a group pair."""

    us: int
    them: int
    won_us: int
    won_them: int
    ties: int
    series_tie: bool

    @property
    def winner(self) -> str | None:
        """``"us"``, ``"them"``, or ``None`` on the book's series tie."""
        if self.series_tie:
            return None
        return "us" if self.us > self.them else "them"


def tally(scores: Sequence[tuple[int, int]], natural: str, tie_score: int) -> SeriesStanding:
    """Group totals from per-sub-game ``(cop, thief)`` scores.

    Each sub-game's points go to whichever group played that role under the
    schedule; a sub-game whose two scores are equal — a technical loss is the
    ordinary case — is a counted tie with no winner. A level series adds
    ``tie_score`` to *both* totals rather than replacing them, exactly as the
    reference's ``aggregate`` does.
    """
    us = them = won_us = won_them = ties = 0
    for number, (cop, thief) in enumerate(scores, start=1):
        ours = cop if role_for(natural, number) == "police" else thief
        theirs = cop + thief - ours
        us += ours
        them += theirs
        if ours > theirs:
            won_us += 1
        elif theirs > ours:
            won_them += 1
        else:
            ties += 1
    series_tie = us == them
    if series_tie:
        us += tie_score
        them += tie_score
    return SeriesStanding(us, them, won_us, won_them, ties, series_tie)
