"""The placement that ends the match, and the cells it is chosen from.

Split out of :mod:`.barriers` so that module keeps to the file-length budget.
Kept together deliberately: the win check runs **before** the value scorer and
before the self-preservation gate, so it must not be able to reach either.
The winning cell frequently scores *worse* on escape reduction than its
neighbours — there is barely any escape left to reduce — and it may well be a
cell that walls us in permanently, which is fine if the game ends on the same
turn. Both gates are right about what they measure and wrong about what to do
once the match is already over.

:mod:`.barriers` re-exports every name here.
"""

import logging
from dataclasses import replace

from ..domain.actions import DEFAULT_MAX_BARRIERS, placement_range
from ..domain.axes import AxisConvention
from ..domain.board import BoardState, Position
from ..domain.outcome import (
    is_capture_by_overlap,
    is_enclosure_capture,
    is_trapping_capture,
)

logger = logging.getLogger(__name__)


def candidates(state: BoardState, axes: AxisConvention) -> list[Position]:
    """Cells the cop may seal this turn, in a stable order.

    Sorted before anything reads them: :func:`placement_range` returns a
    ``frozenset``, and a decision that leaned on set iteration order would be
    reproducible on one machine and nowhere else.
    """
    return sorted(cell for cell in placement_range(state, axes) if not state.is_barrier(cell))


def wins_outright(state: BoardState, at: Position, axes: AxisConvention) -> bool:
    """Whether sealing ``at`` ends the match in our favour this turn.

    Both terminal conditions a barrier can produce, asked of the resulting
    state rather than pattern-matched: a thief standing on a sealed cell, or
    a thief whose four adjacent cells are all closed. Deriving the answer from
    :mod:`..domain.outcome` is deliberate — a Capture Claim must be checkable
    against the board by the opponent, and a claim this module reasoned its
    way to independently is a claim that can disagree with the referee we
    both have to accept.
    """
    sealed = replace(state, barriers=state.barriers | {at})
    return is_trapping_capture(sealed) or is_enclosure_capture(sealed, axes)


def winning_placement(
    state: BoardState, axes: AxisConvention, max_barriers: int = DEFAULT_MAX_BARRIERS
) -> Position | None:
    """A placement that wins outright this turn, if one is legally available.

    Checked before the value scorer and before the self-preservation gate,
    because neither is meaningful once the match is over. A barrier that walls
    us in permanently is fine if the game ends on the same turn.

    Returns ``None`` when the quota is spent: a win that cannot be paid for is
    not a win, and the caller must fall through to ordinary play.

    Also ``None`` when the state is *already* terminal. Without that guard a
    thief standing on a barrier makes :func:`is_trapping_capture` true of
    every resulting state, so the first candidate examined would be returned
    as the winning cell — and a Capture Claim naming a barrier that had
    nothing to do with the capture is a false claim, which disqualifies the
    team at audit. The orchestrator should never ask for an action in a
    finished position, but "should never" is not a guarantee worth a match.
    """
    if state.barriers_used >= max_barriers:
        return None
    if is_trapping_capture(state) or is_capture_by_overlap(state):
        return None
    for cell in candidates(state, axes):
        if wins_outright(state, cell, axes):
            logger.info("winning placement at %s from cop=%s", cell, state.cop)
            return cell
    return None
