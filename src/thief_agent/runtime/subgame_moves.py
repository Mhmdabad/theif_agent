"""Reading the opponent's revealed action, and moving one board by both.

Split from :mod:`.subgame` unchanged. It sits early in the chain because both
the scent work and the audit ask the same question — *what did they say they
did?* — and neither can be answered without the reveal being turned into an
action the board will accept.
"""

from dataclasses import dataclass
from typing import cast

from ..domain.actions import Action, MoveAction, PlaceBarrier, apply_action
from ..domain.board import Move
from ..domain.outcome import is_capture_by_overlap, is_enclosure_capture, is_trapping_capture
from .subgame_state import SubGameState
from .subgame_types import MOVES, UnplayableReveal


@dataclass
class SubGameMoves(SubGameState):
    """The board half of a sub-game: read their reveal, then advance."""

    def peer_move(self, step: int) -> Action | None:
        """What the opponent said they did, once they have said it."""
        opened = self._peer_reveals.get(step)
        if opened is None:
            return None
        if opened.barrier_placed:
            if self.opponent != "police":
                raise UnplayableReveal(
                    f"the thief revealed a barrier at step {step}; only the cop may place "
                    "one, and a board advanced by an illegal action is a board the two "
                    "peers no longer share"
                )
            return PlaceBarrier(at=(opened.barrier_placed[0], opened.barrier_placed[1]))
        if opened.move not in MOVES:
            raise UnplayableReveal(
                f"the {self.opponent} revealed move {opened.move!r} at step {step}, which is "
                "not a move; the board cannot be advanced from a statement it cannot read"
            )
        return MoveAction(move=cast("Move", opened.move))

    def _advance(self, ours: Action, theirs: Action | None) -> None:
        """Apply both moves to one board.

        Ours first, then theirs, and both against the same starting state as
        far as legality is concerned — the two were chosen simultaneously and
        neither saw the other. Applying them in sequence is the only thing a
        single board can do; what must not happen is either side *deciding*
        with knowledge of the other, and the ceremony above is what prevents it.
        """
        self.state = apply_action(self.state, self._agent(self.role), ours, self.axes)
        if theirs is not None:
            self.state = apply_action(self.state, self._agent(self.opponent), theirs, self.axes)

    def _captured(self) -> bool:
        """Any of the three capture conditions the rulebook defines."""
        return (
            is_capture_by_overlap(self.state)
            or is_trapping_capture(self.state)
            or is_enclosure_capture(self.state, self.axes)
        )
