"""The coordinate convention, negotiated per match.

Two values in the shared config decide how a ``(row, col)`` pair is read:

``axis_origin_corner``
    Which physical corner holds cell ``(0, 0)``. It fixes the growth direction
    of each axis and therefore which offset each compass move applies. Under
    the default ``top-left`` the vertical axis grows downward, so ``N``
    decreases ``row``.

``axis_start_index``
    The number each axis counts from. Default ``0``.

Both are negotiable, and both **must be identical on the two peers**. If one
side counts from 0 and the other from 1, ``[3,3]`` denotes two different cells
and the match becomes incoherent — which is why these live in the signed
``game.json`` and are covered by the ``config_sha256`` exchanged before the
first move, never hard-coded.

Internally the board is always stored 0-indexed. ``start_index`` is applied only
at the wire boundary, so array indexing never has to think about it.
"""

from dataclasses import dataclass
from typing import Any, Literal, get_args

from .board import Move, Position

OriginCorner = Literal["top-left", "top-right", "bottom-left", "bottom-right"]
"""Which corner holds cell ``(0, 0)``."""

ORIGIN_CORNERS: tuple[OriginCorner, ...] = get_args(OriginCorner)


@dataclass(frozen=True, slots=True)
class AxisConvention:
    """How to read a ``(row, col)`` pair, as agreed with the opponent."""

    origin_corner: OriginCorner = "top-left"
    start_index: int = 0

    def __post_init__(self) -> None:
        if self.origin_corner not in ORIGIN_CORNERS:
            raise ValueError(
                f"origin_corner must be one of {ORIGIN_CORNERS}, got {self.origin_corner!r}"
            )
        if self.start_index < 0:
            raise ValueError(f"start_index must be >= 0, got {self.start_index}")

    @classmethod
    def from_config(cls, board_and_agents: dict[str, Any]) -> "AxisConvention":
        """Build from the ``board_and_agents`` section of the shared config."""
        return cls(
            origin_corner=board_and_agents.get("axis_origin_corner", "top-left"),
            start_index=board_and_agents.get("axis_start_index", 0),
        )

    @property
    def row_grows_down(self) -> bool:
        """Whether increasing ``row`` moves south."""
        return self.origin_corner.startswith("top")

    @property
    def col_grows_right(self) -> bool:
        """Whether increasing ``col`` moves east."""
        return self.origin_corner.endswith("left")

    @property
    def deltas(self) -> dict[Move, Position]:
        """Row/column offset for each move under this convention."""
        vertical = 1 if self.row_grows_down else -1
        horizontal = 1 if self.col_grows_right else -1
        return {
            "N": (-vertical, 0),
            "S": (vertical, 0),
            "E": (0, horizontal),
            "W": (0, -horizontal),
            "STAY": (0, 0),
        }

    def to_external(self, pos: Position) -> Position:
        """Convert an internal 0-indexed cell to the agreed wire form."""
        row, col = pos
        return (row + self.start_index, col + self.start_index)

    def from_external(self, pos: Position) -> Position:
        """Convert an agreed wire cell back to internal 0-indexed form."""
        row, col = pos
        return (row - self.start_index, col - self.start_index)
