"""Re-walking the revealed history on the board both peers agreed to.

The evidence record one step leaves behind, and the replay that turns a
sequence of them back into positions. :mod:`.scent_audit` audits what this
produces; keeping the walk here means the order the board is advanced in is
stated once, next to the record it consumes.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from .actions import Action, apply_action
from .axes import AxisConvention
from .board import Agent, BoardState, Position
from .rules import advance_turn, position_of
from .scent_audit_wire import ScentFieldError


@dataclass(frozen=True, slots=True)
class StepPlay:
    """One step as the audit sees it: both actions, and what they disclosed.

    Frozen because it is evidence. The audit's whole claim is that these are
    the values that crossed the wire, and a record the auditor could edit
    proves nothing about the peer who sent it.
    """

    step: int
    ours: Action
    theirs: Action | None
    disclosed: dict[str, float] | None


def _agent(role: str) -> Agent:
    return "cop" if role == "police" else "thief"


def _walk(
    start: BoardState, axes: AxisConvention, role: str, plays: Sequence[StepPlay]
) -> Iterator[tuple[StepPlay, Position, Position]]:
    """Replay the match, yielding where each side stood after its own action.

    The order mirrors :class:`~..runtime.subgame.SubGame` exactly — turn
    counter, our action, then theirs — because a reconstruction that advanced
    the board differently from the loop that played it would report an honest
    peer as a forger.

    Raises:
        ScentFieldError: naming the step at which the revealed history stopped
            being playable. Every later step is unauditable rather than clean.
    """
    mine, yours = _agent(role), _agent("thief" if role == "police" else "police")
    state = start
    for play in plays:
        try:
            state = advance_turn(state)
            state = apply_action(state, mine, play.ours, axes)
            here = position_of(state, mine)
            if play.theirs is not None:
                state = apply_action(state, yours, play.theirs, axes)
        except ValueError as exc:
            raise ScentFieldError(
                f"step {play.step}: the revealed move cannot be replayed on the agreed "
                f"board ({exc}); from here the two peers no longer share a board"
            ) from exc
        yield play, here, position_of(state, yours)


def replay(
    start: BoardState, axes: AxisConvention, role: str, plays: Sequence[StepPlay]
) -> list[tuple[Position, Position]]:
    """Where both sides stood after acting, one entry per step.

    Raises:
        ScentFieldError: if the revealed history is not playable.
    """
    return [(here, there) for _, here, there in _walk(start, axes, role, plays)]
