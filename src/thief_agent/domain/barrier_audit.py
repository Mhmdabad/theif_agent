"""Re-deriving the cop's barriers, and the board every step was sealed against.

Two jobs that turn out to be one. The audit in :mod:`..infra.ceremony` needs
the board each step committed against, and cannot invent it — a reconstruction
bug there would be indistinguishable from a forgery. On this side of the match
the board only changes in ways the log already states: the cop moves, the thief
moves, and the cop places barriers. So replaying the declared barriers *is* the
reconstruction.

**Barriers are the only irreversible thing in the game.** A move can be undone
by moving back; a barrier stands for the rest of the match and shrinks the
thief's world permanently. That makes a misdeclared barrier the most valuable
rewrite available to either side, and it is why the rulebook singles out
barrier declarations for re-verification rather than trusting the step digest
alone.

The digest check in :func:`~..infra.ceremony.audit_opponent` already proves
each step's *record* is the one committed to. What it cannot see is whether the
sequence of records is a **possible history**: a quota exceeded across the
series, a barrier laid twice on one cell, a set that shrinks. Each of those has
every step individually verifying and the match as a whole impossible.

This module is cop-only. The thief places no barriers, so there is nothing on
that side to replay — the thief verifies these same declarations against the
cop's log using its own copy of the record.
"""

from dataclasses import dataclass

from ..infra.ceremony import Reveal
from .actions import DEFAULT_MAX_BARRIERS
from .board import BoardState, Position


@dataclass(frozen=True, slots=True)
class BarrierHistory:
    """Every barrier the log declares, and whether it could have happened."""

    placements: tuple[tuple[int, Position], ...]
    problems: tuple[str, ...] = ()

    @property
    def sound(self) -> bool:
        return not self.problems

    def __str__(self) -> str:
        if self.sound:
            return f"{len(self.placements)} barriers declared, all consistent"
        return (
            f"{len(self.placements)} barriers declared, {len(self.problems)} problems: "
            + "; ".join(self.problems)
        )


def _cell(opened: Reveal) -> Position | None:
    """The barrier this reveal declares, as a position, or ``None``.

    Cells arrive from the wire as lists; the rest of the domain speaks tuples,
    and a list would compare unequal to every position in a barrier set.
    """
    placed = opened.barrier_placed
    return (placed[0], placed[1]) if placed else None


def declared(reveals: dict[int, Reveal]) -> tuple[tuple[int, Position], ...]:
    """Every barrier the reveals declare, oldest first."""
    return tuple(
        (step, cell) for step in sorted(reveals) if (cell := _cell(reveals[step])) is not None
    )


def replay(
    reveals: dict[int, Reveal],
    start: frozenset[Position] = frozenset(),
    quota: int = DEFAULT_MAX_BARRIERS,
    grid_size: int | None = None,
) -> BarrierHistory:
    """Walk the declarations forward, reporting any history that cannot be.

    Every problem is collected rather than raised at the first, for the same
    reason the step audit collects: an accusation the opponent can only see
    half of is one they will contest twice.
    """
    problems: list[str] = []
    placements = declared(reveals)
    standing: set[Position] = set(start)
    for step, cell in placements:
        if cell in standing:
            problems.append(f"step {step}: barrier declared at {cell}, already sealed")
        if grid_size is not None and not (0 <= cell[0] < grid_size and 0 <= cell[1] < grid_size):
            problems.append(f"step {step}: barrier declared at {cell}, off a {grid_size} board")
        standing.add(cell)
        if len(standing) - len(start) > quota:
            problems.append(
                f"step {step}: barrier {len(standing) - len(start)} exceeds the agreed quota "
                f"of {quota}; every step verifies and the series is still impossible"
            )
    return BarrierHistory(placements=placements, problems=tuple(problems))


def rebuild_states(
    reveals: dict[int, Reveal],
    trajectory: dict[int, tuple[Position, Position]],
    grid_size: int,
    start: frozenset[Position] = frozenset(),
) -> dict[int, BoardState]:
    """The board each step was sealed against, for the ceremony audit.

    ``trajectory`` gives ``(cop, thief)`` at the start of each step, which both
    peers can derive from the agreed starting squares and the revealed moves.

    **The barrier set is the one in force *before* the step's own placement.**
    A commitment is made against the board the agent was looking at, and it had
    not laid that barrier yet when it chose to. Off by one here re-derives every
    barrier-placing step wrongly and reports a clean cop as a forger.
    """
    states: dict[int, BoardState] = {}
    standing = set(start)
    for step in sorted(reveals):
        if step in trajectory:
            cop, thief = trajectory[step]
            states[step] = BoardState(
                grid_size=grid_size,
                cop=cop,
                thief=thief,
                barriers=frozenset(standing),
                step=step,
            )
        placed = _cell(reveals[step])
        if placed is not None:
            standing.add(placed)
    return states
