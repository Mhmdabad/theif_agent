"""Movement legality — the single authority on what an agent may do.

There is no referee. Each peer runs this module against its own copy of the
state, both to choose its own move and to validate the move its opponent
claims to have made. A divergence here is not a local bug: it is two agents
enforcing different physics on the same match.

The axis convention is a **required** argument, never defaulted. It is
negotiated per match, and silently assuming ``top-left`` against an opponent
playing ``bottom-left`` would produce legal-looking moves in the wrong
direction — the incoherent-match failure the convention exists to prevent.

On ``STAY`` and enclosure
    ``legal_moves`` includes ``STAY`` whenever the agent's own cell is passable.
    That does **not** make the enclosure capture unreachable: the rulebook
    defines it on the adjacent cells specifically — *"a thief imprisoned with no
    legal move at all (all adjacent cells blocked by barriers and/or board
    edges) is likewise considered captured"* — so standing still is not an
    escape from encirclement. Enclosure is therefore a separate predicate over
    neighbours, not the emptiness of this list.
"""

from dataclasses import replace

from .axes import AxisConvention
from .board import MOVES, Agent, BoardState, Move, Position


def position_of(state: BoardState, agent: Agent) -> Position:
    """The cell ``agent`` currently occupies."""
    return state.cop if agent == "cop" else state.thief


def target_of(origin: Position, move: Move, axes: AxisConvention) -> Position:
    """The cell reached by applying ``move`` to ``origin``.

    Returns the cell whether or not it is legal; legality is a separate
    question answered by :func:`is_legal_move`.
    """
    drow, dcol = axes.deltas[move]
    row, col = origin
    return (row + drow, col + dcol)


def is_legal_move(state: BoardState, agent: Agent, move: Move, axes: AxisConvention) -> bool:
    """Whether ``agent`` may play ``move`` from the current state.

    A move is legal when its target cell is on the board and not blocked by a
    barrier. Agent occupancy is not a blocker: the cop moving onto the thief's
    cell is precisely how a capture happens.
    """
    return state.is_free(target_of(position_of(state, agent), move, axes))


def legal_moves(state: BoardState, agent: Agent, axes: AxisConvention) -> list[Move]:
    """Every move ``agent`` may legally play, in a stable order.

    Order follows :data:`~.board.MOVES` so that a policy iterating this list
    behaves identically across runs and across the two peers, which matters for
    replay determinism.
    """
    return [move for move in MOVES if is_legal_move(state, agent, move, axes)]


def blocked_neighbours(state: BoardState, pos: Position, axes: AxisConvention) -> int:
    """How many of the four orthogonal neighbours of ``pos`` are impassable.

    Counts both barriers and the board edge. A count of four is the encirclement
    condition the enclosure capture is defined on.
    """
    return sum(not state.is_free(target_of(pos, move, axes)) for move in MOVES if move != "STAY")


class IllegalMoveError(ValueError):
    """Raised when a move violates the physics both peers enforce."""


def apply_move(state: BoardState, agent: Agent, move: Move, axes: AxisConvention) -> BoardState:
    """Apply ``move`` and return a **new** state.

    Never mutates: the Commit hash is taken over a state snapshot, so a state
    that changed in place would break integrity verification.

    The step counter is deliberately untouched. A step is a *full* turn — both
    sides having moved — so advancing it belongs to turn management rather than
    to a single agent's action.

    Raises:
        IllegalMoveError: if the move is not legal from this state.
    """
    origin = position_of(state, agent)
    if move == "STAY" and origin in state.barriers:
        destination = origin
    else:
        if not is_legal_move(state, agent, move, axes):
            target = target_of(origin, move, axes)
            raise IllegalMoveError(f"{agent} cannot play {move}: {origin} -> {target}")
        destination = target_of(origin, move, axes)
    if agent == "cop":
        return replace(state, cop=destination)
    return replace(state, thief=destination)


def advance_turn(state: BoardState) -> BoardState:
    """Return a new state with the turn counter incremented.

    Called once both sides have moved. Scent decay and the survival count are
    both defined on full turns, so this is the boundary they key off.
    """
    return replace(state, step=state.step + 1)
