"""Match outcomes, their precedence, and the points they award.

Every value here is **fixed** in Appendix F: deviating from a fixed value
disqualifies the team, so the table is validated against the book defaults on
load rather than trusted.

Precedence matters. More than one condition can hold on the same turn — a cop
can seal the thief's last escape on the very turn the survival count reaches
its threshold — and the two readings award opposite results. Leaving that to
whichever predicate a call site happens to check first is how the two peers end
up disagreeing about a match they both played correctly.
"""

from enum import Enum
from typing import Any

from .axes import AxisConvention
from .board import BoardState
from .outcome import (
    DEFAULT_SURVIVAL_THRESHOLD,
    is_capture_by_overlap,
    is_enclosure_capture,
    is_survival,
    is_trapping_capture,
)


class Outcome(Enum):
    """How a sub-game finished."""

    ONGOING = "ongoing"
    CAPTURE = "capture"
    SURVIVAL = "survival"
    TECHNICAL_LOSS = "technical_loss"


BOOK_SCORES: dict[Outcome, tuple[int, int]] = {
    Outcome.CAPTURE: (20, 5),
    Outcome.SURVIVAL: (5, 10),
    Outcome.TECHNICAL_LOSS: (0, 0),
    Outcome.ONGOING: (0, 0),
}
"""Appendix F scoring, as ``(cop, thief)``. All entries are *fixed*."""

BOOK_TIE_SCORE = 2
"""Awarded to each side when a whole series ends level. *Fixed*."""


def evaluate(
    state: BoardState,
    axes: AxisConvention,
    survival_threshold: int = DEFAULT_SURVIVAL_THRESHOLD,
) -> Outcome:
    """Classify a board position, capture taking precedence over survival.

    A technical loss is never returned: it is a protocol event, not a board
    configuration, and is supplied by the caller that observed it.

    **Capture wins ties.** If the cop closes the last escape on the same turn
    the survival count matures, the thief was captured. Survival requires
    surviving *without being captured*, so a turn containing a capture cannot
    also be a survival.
    """
    if (
        is_capture_by_overlap(state)
        or is_trapping_capture(state)
        or is_enclosure_capture(state, axes)
    ):
        return Outcome.CAPTURE
    if is_survival(state, axes, survival_threshold):
        return Outcome.SURVIVAL
    return Outcome.ONGOING


def scores_for(
    outcome: Outcome, table: dict[Outcome, tuple[int, int]] | None = None
) -> tuple[int, int]:
    """Points awarded as ``(cop, thief)``."""
    return (table or BOOK_SCORES)[outcome]


def scores_from_config(scoring: dict[str, Any]) -> dict[Outcome, tuple[int, int]]:
    """Build the table from the ``scoring`` section of the shared config.

    Raises:
        ValueError: if any value deviates from Appendix F. These are *fixed*
            parameters — a mismatch is not a house rule, it is a
            disqualification waiting to be discovered at audit.
    """
    table = {
        Outcome.CAPTURE: (int(scoring["capture_cop"]), int(scoring["capture_thief"])),
        Outcome.SURVIVAL: (int(scoring["survival_cop"]), int(scoring["survival_thief"])),
        Outcome.TECHNICAL_LOSS: (int(scoring["technical_loss"]),) * 2,
        Outcome.ONGOING: (0, 0),
    }
    for outcome, value in table.items():
        if value != BOOK_SCORES[outcome]:
            raise ValueError(
                f"{outcome.value} scores {value}, but Appendix F fixes "
                f"{BOOK_SCORES[outcome]}; fixed values may not be renegotiated"
            )
    if int(scoring["tie_score"]) != BOOK_TIE_SCORE:
        raise ValueError(f"tie_score must be {BOOK_TIE_SCORE}, got {scoring['tie_score']}")
    return table
