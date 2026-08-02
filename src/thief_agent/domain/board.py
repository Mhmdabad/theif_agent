"""Core board types for the cops-and-robbers arena.

The board is a discrete square grid. A cell is addressed as ``(row, col)``.
With the default axis convention the origin sits in the **top-left** corner and
the vertical axis grows downward, so ``N`` decreases ``row``. That convention is
negotiable per match and is made configurable separately; the deltas here are
the book default.

``BoardState`` is **frozen**. Immutability is not stylistic: the Commit hash of
the Commit-Reveal protocol is taken over a specific state snapshot, so a state
that could mutate underneath a commitment would break integrity verification.
Transitions return a new instance rather than editing one in place.
"""

from dataclasses import dataclass
from typing import Literal, get_args

Position = tuple[int, int]
"""A cell, addressed as ``(row, col)``."""

Move = Literal["N", "S", "E", "W", "STAY"]
"""The complete legal action set. Diagonal movement does not exist."""

MOVES: tuple[Move, ...] = get_args(Move)
"""All moves, for iteration. Order is stable so policies stay deterministic."""

DELTAS: dict[Move, Position] = {
    "N": (-1, 0),
    "S": (1, 0),
    "E": (0, 1),
    "W": (0, -1),
    "STAY": (0, 0),
}
"""Row/column offset per move, under the default top-left origin."""


@dataclass(frozen=True, slots=True)
class Barrier:
    """A single barrier placement, as declared to the opponent.

    ``BoardState`` stores barrier *positions* for O(1) lookup; this record is
    the declaration and audit form, carrying the step it was placed at. Every
    placement must be announced truthfully with its exact location, and the
    end-of-match audit re-checks each declaration against what was committed.
    """

    at: Position
    placed_at_step: int


@dataclass(frozen=True, slots=True)
class BoardState:
    """An immutable snapshot of the arena.

    Attributes:
        grid_size: Side of the square grid.
        cop: The cop's cell.
        thief: The thief's cell.
        barriers: Impassable cells. Irreversible for the rest of the match.
        step: Steps completed so far.
    """

    grid_size: int
    cop: Position
    thief: Position
    barriers: frozenset[Position] = frozenset()
    step: int = 0

    def __post_init__(self) -> None:
        if self.grid_size < 1:
            raise ValueError(f"grid_size must be >= 1, got {self.grid_size}")
        if self.step < 0:
            raise ValueError(f"step must be >= 0, got {self.step}")
        for name, pos in (("cop", self.cop), ("thief", self.thief)):
            if not self.in_bounds(pos):
                raise ValueError(f"{name} position {pos} is off a {self.grid_size} board")
        for pos in self.barriers:
            if not self.in_bounds(pos):
                raise ValueError(f"barrier {pos} is off a {self.grid_size} board")

    @property
    def barriers_used(self) -> int:
        """Barriers placed so far, checked against the quota.

        Derived rather than stored: only the cop places barriers, so the count
        is always the size of the set and cannot drift out of step with it.
        """
        return len(self.barriers)

    def in_bounds(self, pos: Position) -> bool:
        """Whether ``pos`` lies on the board."""
        row, col = pos
        return 0 <= row < self.grid_size and 0 <= col < self.grid_size

    def is_barrier(self, pos: Position) -> bool:
        """Whether ``pos`` is blocked by a barrier."""
        return pos in self.barriers

    def is_free(self, pos: Position) -> bool:
        """Whether ``pos`` is on the board and not blocked.

        Agent occupancy is deliberately not considered: the cop capturing the
        thief means moving onto the thief's cell.
        """
        return self.in_bounds(pos) and not self.is_barrier(pos)
