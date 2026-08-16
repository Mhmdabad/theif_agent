"""Board geometry and move legality (book ch.3).

App. F fixes the move set permanently: one orthogonal step, or stay. **No diagonals** — an
illegal move is rejected by the opposing agent, which enforces the physics on its own side.
Barriers are placed only by the cop, only in a turn where it forgoes movement, only on its own
cell or one orthogonally adjacent, and they are impassable **to both players for the rest of the
game**.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

Cell = tuple[int, int]

# Wire spelling of each action. The reference sends "MOVE:N"; STAY is the fifth legal action and
# is what a cop does on a turn it spends placing a barrier.
MOVES: dict[str, Cell] = {
    "MOVE:N": (-1, 0),
    "MOVE:S": (1, 0),
    "MOVE:W": (0, -1),
    "MOVE:E": (0, 1),
    "STAY": (0, 0),
}
ORTHOGONAL = ("MOVE:N", "MOVE:S", "MOVE:W", "MOVE:E")
Move = str


@dataclass(frozen=True)
class Board:
    """A square grid with the origin at the top-left and axes starting at 0 (App. F table 13)."""

    size: int

    def in_bounds(self, cell: Cell) -> bool:
        r, c = cell
        return 0 <= r < self.size and 0 <= c < self.size

    def step(self, cell: Cell, move: Move) -> Cell:
        dr, dc = MOVES[move]
        return (cell[0] + dr, cell[1] + dc)

    def neighbours(self, cell: Cell) -> list[Cell]:
        """The four orthogonally adjacent cells that exist on the board. Never diagonals."""
        return [self.step(cell, m) for m in ORTHOGONAL if self.in_bounds(self.step(cell, m))]

    def legal_moves(self, cell: Cell, barriers: Iterable[Cell]) -> list[Move]:
        """Every action legal from `cell`, in a fixed order so a seeded policy is reproducible.

        STAY is always legal: it is how a cop spends a turn placing a barrier, and it is a legal
        thief action too. It is therefore never true that an agent has *no* action — but it can
        be true that a thief has no legal **move**, which is a capture (rule 47) and is decided
        by `boxed_in` below rather than here.
        """
        blocked = set(barriers)
        out = [m for m in ORTHOGONAL
               if self.in_bounds(self.step(cell, m)) and self.step(cell, m) not in blocked]
        return out + ["STAY"]

    def boxed_in(self, cell: Cell, barriers: Iterable[Cell]) -> bool:
        """True when every orthogonal neighbour is a barrier or off the board.

        App. E rule 47: a thief with no legal move at all is captured. Staying still does not
        rescue it — the rule is about movement, and a thief that cannot move has been trapped.
        """
        blocked = set(barriers)
        return all(n in blocked for n in self.neighbours(cell))

    def barrier_targets(self, cop: Cell, barriers: Iterable[Cell]) -> list[Cell]:
        """Where the cop may place a barrier: its own cell, or one step orthogonally.

        Book ch.3, the barrier rule. Placing on its own cell is legal and is how a cop walls a
        corridor behind itself; placing on the thief's current cell is a capture (rule 46), which
        the cop cannot know in advance under hidden positions — it is a gamble, and the thief is
        obliged to answer honestly when it lands.
        """
        blocked = set(barriers)
        candidates = [cop] + self.neighbours(cop)
        return [c for c in candidates if self.in_bounds(c) and c not in blocked]


def chebyshev(a: Cell, b: Cell) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
