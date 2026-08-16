"""Whether a series is the pairing's one counted game.

Rule 52 counts exactly one series per opponent and allows any number of
warm-ups. A reader holding two series between the same pair must be told which
is which by the documents themselves -- otherwise the tiebreak is a filename or
a timestamp, and neither is evidence.

The cohort's example bundle carries this block; the lecturer's sample does not.
It costs a reader nothing to ignore and costs us a graded match to omit, so it
is here.
"""

from typing import Any

__all__ = ["league_block"]


def league_block(counted: bool) -> dict[str, Any]:
    """The league standing of this series, in the cohort's shape."""
    return {
        "authority": "book App. E rule 52 — the one counted series of this pairing",
        "counted": counted,
        "reason": "counted" if counted else "friendly",
    }
