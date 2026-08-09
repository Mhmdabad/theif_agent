"""Board geometry the thief's policy measures candidates with.

Two questions about a cell, both answered from the board alone: how far it is
from somewhere, and how many ways there are out of it. Neither depends on the
brain's state, which is why they live apart from it and why the ranking can be
read without them and they can be tested without the ranking.
"""

from ..domain.axes import AxisConvention
from ..domain.board import MOVES, BoardState, Position
from ..domain.rules import target_of

__all__ = ["MIN_OPEN_NEIGHBOURS", "manhattan", "open_neighbours"]

MIN_OPEN_NEIGHBOURS = 3
"""Below this many open exits, a cell counts as cramped.

Three rather than two, so the four corners of an open board are already
refused. A corner has degree 2 and costs the cop two barriers; waiting for
degree to fall to 1 means waiting until one of those barriers is placed, by
which point the choice of whether to be there has been made.
"""


def manhattan(a: Position, b: Position) -> int:
    """Steps between two cells, ignoring barriers."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def open_neighbours(state: BoardState, cell: Position, axes: AxisConvention) -> int:
    """How many orthogonal steps out of ``cell`` lead somewhere free.

    The board edge and a barrier close a side equally, which is the whole of
    Appendix D's enclosure pricing: a cell needs four closed sides, and the
    board supplies the difference for nothing.
    """
    return sum(1 for move in MOVES if move != "STAY" and state.is_free(target_of(cell, move, axes)))
