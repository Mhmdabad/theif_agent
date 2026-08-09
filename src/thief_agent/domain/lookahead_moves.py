"""What each side may legally do at a search node, in a stable order.

Split out of :mod:`.lookahead`, which owns the tree and takes this as a
parameter. The search must never be handed an illegal action — it applies
without re-validating, because re-validating every node of a few thousand
would cost more than the search — so this is where legality is settled.

**The cop's barrier options are bounded by the rules, not by taste.** A
placement is limited to the cop's own cell or an orthogonal neighbour, so the
branching factor is at most ten actions rather than the sixty-odd a free
choice of cell would give. The quota is respected too: a cop that has spent
its barriers can only move, and offering placements it cannot make would have
the search plan around a resource it does not have.

Order is fixed — moves in :data:`~.board.MOVES` order, then placements in
compass order — so two searches of the same position expand the same tree in
the same sequence, and the move a match plays is reproducible.
"""

from collections.abc import Sequence
from dataclasses import replace

from .actions import Action, MoveAction, PlaceBarrier
from .axes import AxisConvention
from .board import MOVES, Agent, BoardState, Position
from .rules import legal_moves, target_of

__all__ = ["candidates", "sealable"]


def candidates(
    state: BoardState, agent: Agent, axes: AxisConvention, quota: int
) -> Sequence[Action]:
    """Every action ``agent`` may take from ``state``, cheapest branching first.

    ``quota`` is the barrier allowance from the agreed configuration. Only the
    cop can place, and only while it has some left.
    """
    actions: list[Action] = [MoveAction(move) for move in legal_moves(state, agent, axes)]
    if agent == "cop" and len(state.barriers) < quota:
        actions.extend(
            PlaceBarrier(at=cell)
            for cell in sealable(state, axes)
            if not _immures(state, cell, axes)
        )
    return actions


def _immures(state: BoardState, cell: Position, axes: AxisConvention) -> bool:
    """Whether sealing ``cell`` would leave the cop with nowhere to go.

    A hard filter rather than a scoring preference, because the cost is not a
    bad position — it is ``NoLegalActionError``, which ends the match as a
    technical loss scoring **zero for both sides**. A search left to discover
    this through the evaluation found it only sometimes, and once is enough:
    the cop sealed itself into a pocket in a live rehearsal and both peers lost
    the series. Sealing the thief's cell is exempt: that is rule 46's trapping
    capture, the game is already won, and no move is needed afterwards.
    """
    if cell == state.thief:
        return False
    walled = replace(state, barriers=state.barriers | {cell})
    return not legal_moves(walled, "cop", axes)


def sealable(state: BoardState, axes: AxisConvention) -> list[Position]:
    """Cells the cop may seal this turn: its own, and its orthogonal neighbours.

    A cell already sealed is skipped as a no-op. The thief's own cell is
    **not** skipped: sealing it is rule 46's trapping capture, which is a
    winning move and precisely the one a search must be allowed to find.
    """
    here = state.cop
    reachable = [here, *(target_of(here, move, axes) for move in MOVES if move != "STAY")]
    return [cell for cell in reachable if cell not in state.barriers and _on(cell, state.grid_size)]


def _on(cell: Position, grid_size: int) -> bool:
    row, col = cell
    return 0 <= row < grid_size and 0 <= col < grid_size
