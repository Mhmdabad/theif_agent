"""Whether a series is the pairing's one counted game.

Rule 52 counts exactly one series per opponent and allows any number of
warm-ups. A reader holding two series between the same pair must be told which
is which by the documents themselves -- otherwise the tiebreak is a filename or
a timestamp, and neither is evidence.

The cohort's example bundle carries this block; the lecturer's sample does not.
It costs a reader nothing to ignore and costs us a graded match to omit, so it
is here.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .report_document import Report

__all__ = ["league_block"]


def league_block(counted: bool) -> dict[str, Any]:
    """The league standing of this series, in the cohort's shape."""
    return {
        "authority": "book App. E rule 52 — the one counted series of this pairing",
        "counted": counted,
        "reason": "counted" if counted else "friendly",
    }


def final_result(report: "Report", standing: dict[str, Any], us: str, them: str) -> dict[str, Any]:
    """The aggregate plus the kit's counted-league declarations."""
    first = report.first_meeting_between_groups
    winner = standing.get("winner_group")
    return {
        "total_score": standing.get("total_score", {}),
        "sub_games_won": standing.get("sub_games_won", {}),
        "ties": standing.get("ties", 0),
        "winner_group": winner,
        "series_tie": standing.get("series_tie", False),
        "tokens_total_series": {us: report.total_tokens, them: 0},
        "games_played_including_this": {
            us: report.games_played_including_this,
            them: report.opponent_games_played_including_this,
        },
        "first_meeting_between_groups": first,
        "diversity_reward_applied": {
            us: bool(report.counted and first and winner == us),
            them: bool(report.counted and first and winner == them),
        },
    }
