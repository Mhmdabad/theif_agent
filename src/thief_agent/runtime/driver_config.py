"""Reading the private config into the pieces a match is assembled from.

The parsing half of :mod:`.driver`: the parts that turn a private TOML dict and
the shared parameters into a :class:`~..infra.declaration.Team` or a
:class:`~..domain.board.BoardState`. They live here rather than beside the
wiring because they are the only pieces of the driver that can silently produce
a *wrong* match rather than a failed one, and they are covered accordingly.
"""

from typing import Any

from ..domain.board import BoardState
from ..infra.declaration import Team
from ..shared.appendix_f import book_int


def _side(block: dict[str, Any]) -> Team:
    """One side of the declaration, from a config block shaped like ``[game]``.

    Both sides are read the same way so the opponent's details can be pasted in
    the shape ours are already written in. FR-7.28 wants four repository links
    and :class:`Team` refuses a partial set, which is the right moment to find
    out — before a match rather than while writing the result nobody can trace.
    """
    repos = block.get("repos", {})
    return Team(
        name=str(block.get("group_name", "")),
        members=tuple(str(m) for m in block.get("members", [])),
        cop_repo=str(repos.get("cop", "")),
        thief_repo=str(repos.get("thief", "")),
    )


def _us(private: dict[str, Any]) -> Team:
    """Our own side, from ``[game]`` — where it already lives.

    Read from there rather than from a second ``[teams.us]`` block, because two
    places to state our own repositories is two places to disagree, and the
    declaration would carry whichever the code happened to read.
    """
    return _side(private.get("game", {}))


def _them(private: dict[str, Any]) -> Team:
    """The opponent, from ``[teams.them]`` — agreed with them beforehand.

    Nothing can derive this: their repositories and their members are theirs to
    state. It is the one section that must be edited per opponent.
    """
    return _side(private.get("teams", {}).get("them", {}))


def _cell(value: object, fallback: tuple[int, int]) -> tuple[int, int]:
    """A start position from JSON, which has lists rather than tuples."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (int(value[0]), int(value[1]))
    return fallback


def _max_moves(parameters: dict[str, Any]) -> int:
    """How many steps a sub-game may run to, from the agreed configuration.

    The fallback is the book's own value rather than a number typed here. It was
    ``40``, which is not a rounding of Appendix F table 6's minimum of 35 but a
    different rule — unreachable, because :func:`~...shared.config.load`
    validates the key before this runs, and exactly the drift the ``book_value``
    doctrine exists to prevent. A default that disagrees with the book is one
    that becomes the truth the day the validation moves.
    """
    movement = parameters.get("movement_and_barriers", {})
    return int(movement.get("max_moves", book_int("movement_and_barriers", "max_moves")))


def _start_board(board: dict[str, Any]) -> BoardState:
    """The opening position, from the shared ``[board_and_agents]`` table."""
    return BoardState(
        grid_size=int(board.get("grid_size", 8)),
        cop=_cell(board.get("cop_start"), (0, 0)),
        thief=_cell(board.get("thief_start"), (6, 5)),
        barriers=frozenset(),
        step=0,
    )
