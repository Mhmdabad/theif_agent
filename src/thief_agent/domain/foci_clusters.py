"""Where a belief map concentrates, and what counts as one place.

Clusters are found by adjacency rather than by ranking cells. Two cells of a
single hill are not two foci, and a top-N list would report them as such.
"""

from dataclasses import dataclass

from .belief import Belief
from .board import Position

BACKGROUND = 1.0
"""Multiple of the uniform share a cell must exceed to join a focus.

The floor has to be the uniform share, not a small absolute number. Silence is
neutral in the belief map, so no cell ever falls to zero — with an absolute
floor every free cell clears it, they are all adjacent, and the whole board
reports as one focus whose "peak" then teleports across the map as evidence
arrives. A cell at the uniform share is one the evidence has not touched; a
cell above it is one the evidence points at.

A consequence worth stating: a uniform prior has **no** foci at all, which is
correct. Nothing is worth committing to before any evidence has arrived.
"""


@dataclass(frozen=True, slots=True)
class Focus:
    """One connected cluster of belief."""

    peak: Position
    mass: float
    cells: tuple[Position, ...]

    def __str__(self) -> str:
        return f"{self.peak} holding {self.mass:.0%} over {len(self.cells)} cell(s)"


def _neighbours(cell: Position) -> tuple[Position, ...]:
    row, col = cell
    return ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1))


def foci(belief: Belief, background: float = BACKGROUND) -> list[Focus]:
    """Connected clusters of belief, heaviest first.

    Only cells carrying more than the uniform share take part; see
    :data:`BACKGROUND`. Adjacency rather than ranking: the four cells around a
    peak belong to that peak, and reporting them as separate foci would turn
    one hill into five. Ties resolve by position so two peers reading the same
    distribution list them in the same order.
    """
    if not belief.mass:
        return []
    floor = background / len(belief.mass)
    live = {cell for cell, mass in belief.mass.items() if mass > floor}
    found: list[Focus] = []
    while live:
        seed = min(live)
        cluster = {seed}
        queue = [seed]
        while queue:
            for neighbour in _neighbours(queue.pop()):
                if neighbour in live and neighbour not in cluster:
                    cluster.add(neighbour)
                    queue.append(neighbour)
        live -= cluster
        peak = min(cluster, key=lambda cell: (-belief.at(cell), cell))
        found.append(
            Focus(
                peak=peak,
                mass=sum(belief.at(cell) for cell in cluster),
                cells=tuple(sorted(cluster)),
            )
        )
    found.sort(key=lambda focus: (-focus.mass, focus.peak))
    return found
