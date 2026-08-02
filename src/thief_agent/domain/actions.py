"""What an agent may do on its turn, and how a turn is applied.

A turn is **exactly one** action. The cop may move, or it may forfeit movement
to place a barrier — never both. That exclusivity is the rule this module
enforces, and it is enforced *by construction*: an action is one variant or the
other, so there is no representable value meaning "move and place". A validator
that could be forgotten is a validator that will be.
"""

from dataclasses import dataclass, replace
from typing import assert_never

from .axes import AxisConvention
from .board import Agent, BoardState, Move, Position
from .rules import apply_move


@dataclass(frozen=True, slots=True)
class MoveAction:
    """Relocate one cell, or stand still."""

    move: Move


@dataclass(frozen=True, slots=True)
class PlaceBarrier:
    """Forfeit movement to seal a cell.

    Only the cop may do this. The cop does not relocate on such a turn — that
    forfeit is the cost that makes each placement a resource decision rather
    than a free ability.
    """

    at: Position


Action = MoveAction | PlaceBarrier
"""One turn's worth of intent."""


class IllegalActionError(ValueError):
    """Raised when an action is not available to this agent in this state."""


DEFAULT_MAX_BARRIERS = 14
"""Appendix F barrier quota. A *minimum*: raisable by agreement, never lower."""


def place_barrier(
    state: BoardState,
    at: Position,
    axes: AxisConvention,
    max_barriers: int = DEFAULT_MAX_BARRIERS,
) -> BoardState:
    """Seal ``at`` and return a new state, leaving the cop where it stands.

    A sealed cell is impassable for **both** players and can never be
    reopened: the returned state's barrier set is a superset of the old one,
    because the only operation available is union. There is deliberately no
    inverse.

    Raises:
        IllegalActionError: if the cell is off the board, already sealed, or
            the quota is exhausted.
    """
    del axes  # placement geometry is validated in a later change
    if not state.in_bounds(at):
        raise IllegalActionError(f"barrier {at} is off a {state.grid_size} board")
    if state.is_barrier(at):
        raise IllegalActionError(f"barrier {at} is already placed; barriers are permanent")
    if state.barriers_used >= max_barriers:
        raise IllegalActionError(
            f"barrier quota exhausted: {state.barriers_used}/{max_barriers} used"
        )
    return replace(state, barriers=state.barriers | {at})


def apply_action(
    state: BoardState,
    agent: Agent,
    action: Action,
    axes: AxisConvention,
    max_barriers: int = DEFAULT_MAX_BARRIERS,
) -> BoardState:
    """Apply one turn's action and return the resulting state.

    Raises:
        IllegalActionError: if the thief attempts to place a barrier.
        IllegalMoveError: if a move is not legal from this state.
    """
    match action:
        case MoveAction(move=move):
            return apply_move(state, agent, move, axes)
        case PlaceBarrier(at=at):
            if agent != "cop":
                raise IllegalActionError("only the cop may place a barrier")
            return place_barrier(state, at, axes, max_barriers)
        case _:  # pragma: no cover - unreachable while Action stays closed
            assert_never(action)
