"""The series standing, phrased the one way both peers can agree to it.

Split from :mod:`.match` for the line budget, and because the block below is
wire format rather than bookkeeping: it travels inside the rule 35 claim and
in ``result_<game_id>.json``, so its keys are part of what two peers must
reproduce byte for byte.

Keyed by **group name** rather than "us"/"them" — a claim phrased from the
sender's point of view would be two different claims and could never match.
Both peers name the same two groups, so both produce identical bytes,
including the tie rule's addition and the name of whoever opened as police.
"""

from collections.abc import Sequence

from ..domain.alternation import tally
from ..domain.scoring import BOOK_TIE_SCORE

__all__ = ["series_block"]


def series_block(
    scores: Sequence[tuple[int, int]], natural: str, us: str, them: str
) -> dict[str, object]:
    """The series summed the way the book scores a group pair.

    Args:
        scores: ``(cop, thief)`` per sub-game, in played order.
        natural: the role *we* played in sub-game 1.
        us: our group's name; ``them``: the opponent's.
    """
    if us == them:
        raise ValueError(
            f"both groups are named {us!r}; identical ids would collapse the "
            "two totals into one dict key and corrupt the claim silently"
        )
    standing = tally(scores, natural, BOOK_TIE_SCORE)
    named: dict[str | None, str | None] = {"us": us, "them": them, None: None}
    return {
        "total_score": {us: standing.us, them: standing.them},
        "sub_games_won": {us: standing.won_us, them: standing.won_them},
        "ties": standing.ties,
        "winner_group": named[standing.winner],
        "series_tie": standing.series_tie,
        "police_in_sub_game_1": us if natural == "police" else them,
    }
