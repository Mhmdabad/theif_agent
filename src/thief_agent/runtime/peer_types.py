"""The vocabulary the phases and the plumbing both speak.

Two aliases for the shapes that come off a queue, the claim a mid-game reveal
makes about a result that has not happened yet, and the one exception that
turns a silent opponent into a decision instead of a hang.
"""

from collections.abc import Callable
from typing import Any

Record = dict[str, Any]
Wanted = Callable[[Record], bool]


UNDECIDED = "in_progress"
"""What a mid-game reveal claims about the result: nothing yet."""


class PeerTimeout(RuntimeError):
    """Raised when the opponent did not say something in time.

    The caller converts this into a technical loss. Not retried here: the
    client's budget is the whole allowance, and a second wait on top of it
    would be a deadline nobody agreed to.
    """
