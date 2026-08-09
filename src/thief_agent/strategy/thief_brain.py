"""The thief's decision-making.

Evade the pursuer, breaking ties by **local openness** rather than position.

Distance alone is a trap. A thief maximising distance walks happily into a
corner, because a corner is often the furthest cell from the cop *and* the
place where enclosure costs two barriers instead of four. Running away and
running out of room look identical to a distance metric.

What the thief actually needs is somewhere to go for thirty-five turns, not
merely to be far away now. The obvious way to measure that is reachable area
after the step — and it does not work, for a reason worth stating plainly
because the code carried it as a live tie-break for two issues.

**Reachable area cannot rank moves.** A move changes nothing but the thief's
own cell, so every legal destination is one step from the thief and therefore
in the thief's own connected component; reachable area is a property of that
component, so it returns the same number for every candidate. Always. Not
usually — a sweep of four thousand random positions found zero where it
differed. As a per-candidate term it was noise with a plausible name.

**Local degree** is the signal that does discriminate. Appendix D prices
enclosure by it: two barriers to seal a corner, three on an edge, four in the
open. Stepping onto a degree-2 cell hands the cop a capture at half price, and
it does so before any barrier exists, so nothing else has noticed yet.

**Reachable area still matters — over time rather than across candidates.**
Barriers are permanent, so the region can only shrink, and the rate at which
it shrinks is the cop's containment plan becoming visible. That is a signal
about the *state*, not about any one move, and :mod:`.containment` tracks it.
When the region is closing, degree is promoted above distance: the goal stops
being to get far away and becomes to get somewhere open, because distance
bought inside a pocket the cop is sealing buys nothing at all.

Degree enters the ranking twice. As a **veto** it outranks distance, which is
the module's one deliberately counter-intuitive ordering; it is held honest by
an exemption, because a cramped cell that *strictly increases* distance is a
genuine escape and refusing it means being caught in open board instead. As a
**preference** it ranks equal-distance candidates, which is what the exemption
leaves undecided — and where corner drift would otherwise walk straight back in
through the rule written to stop it.
"""

import logging
from dataclasses import dataclass, replace

from ..domain.board import Agent, BoardState, Move, Position
from .base import NoLegalActionError
from .thief_brain_geometry import MIN_OPEN_NEIGHBOURS, manhattan, open_neighbours
from .thief_brain_ranking import ThiefRanking

__all__ = ["MIN_OPEN_NEIGHBOURS", "ThiefBrain", "manhattan", "open_neighbours"]

logger = logging.getLogger(__name__)


@dataclass
class ThiefBrain(ThiefRanking):
    """Evades the pursuer, refusing cramped cells that gain nothing."""

    @property
    def role(self) -> Agent:
        return "thief"

    def threat(self, state: BoardState, **context: object) -> Position:
        """The cell to run from.

        Runtime supplies the belief peak. Direct callers that omit it receive a
        deterministic uniform-prior choice derived only from board geometry;
        exact opponent truth is never a fallback.
        """
        supplied = context.get("threat")
        if isinstance(supplied, tuple) and len(supplied) == 2:
            return (int(supplied[0]), int(supplied[1]))
        candidates = [
            (row, col)
            for row in range(state.grid_size)
            for col in range(state.grid_size)
            if (row, col) != state.thief and state.is_free((row, col))
        ]
        if not candidates:
            raise NoLegalActionError("belief prior has no possible cop cell")
        return candidates[0]

    def _pick_move(self, state: BoardState, **context: object) -> Move:
        """The best legal move under :meth:`_rank`.

        Not simply the furthest: degree can veto a step and can decide between
        equally distant ones. Whatever survives that, ties break by
        :data:`~..domain.board.MOVES` order rather than randomly, so two peers
        replaying the same match reach the same move.

        The seed goes out on every line rather than once at startup. A match
        transcript is the artefact a bug report is reconstructed from, and a
        seed recorded only in a line that may have been truncated, rotated or
        never captured is a seed the reproduction does not have.

        Raises:
            NoLegalActionError: if no move is legal.
        """
        threat = self.threat(state, **context)
        real_state = state
        state = replace(state, cop=threat)
        available = [m for m in self.options(real_state) if m in self.options(state)]
        if not available:
            available = self.options(real_state)
        if not available:
            raise NoLegalActionError("thief has no legal move")
        self.reach.observe(state, self.axes)
        logger.info("step %d seed=%d %s", state.step, self.seed, self.reach)
        return max(available, key=lambda move: self._rank(state, move, threat))
