"""How a sub-game ends.

Termination is decided from board state, never from either side's assertion.
That matters most for this agent: when the cop issues a Capture Claim the
thief is under a **cryptographic obligation to answer truthfully**, and any
attempt to deny a real capture is exposed at the log audit and disqualifies the
team outright. The honest answer is therefore computed here, directly from the
state, so that no code path exists which could produce a different one.
"""

from .board import BoardState


def is_capture_by_overlap(state: BoardState) -> bool:
    """Whether the cop occupies the thief's cell.

    The primary capture condition: the cop lands on the thief and issues a
    Capture Claim. Derived from position alone, so a claim can be checked
    against the state rather than trusted.
    """
    return state.cop == state.thief
