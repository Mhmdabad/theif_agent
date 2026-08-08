"""Committing to one focus when belief splits in two.

A contradicting hint does not move the peak — it **divides** it. The trail
says south-east, the claim says north, and after the update there are two
plausible clusters with no single argmax worth chasing. The distribution was
always a cloud rather than a point; a contradiction is when that stops being a
technicality.

**The failure this prevents is oscillation, not error.** With two foci of
similar mass, the argmax flips between them as evidence arrives, and an agent
that re-targets every turn walks back and forth between two regions and
arrives at neither. Both foci may be perfectly good guesses; the loss comes
from never committing to one long enough to reach it. Thirty-five turns is not
many, and the turns spent oscillating are the ones that decide the sub-game.

So a chosen focus is **sticky**: it is kept until the evidence against it is
decisive, not merely until something else is momentarily ahead. Switching
requires the rival to lead by :data:`SWITCH_MARGIN`, which is a hysteresis
band rather than a threshold — the same gap that must be crossed to leave is
wider than the gap that would have been enough to pick differently at the
start.
"""

from dataclasses import dataclass, field

from .belief import Belief
from .board import Position
from .foci_clusters import BACKGROUND, Focus, foci

__all__ = ["BACKGROUND", "SWITCH_MARGIN", "Commitment", "Focus", "foci"]

SWITCH_MARGIN = 1.5
"""How far ahead a rival focus must be before we abandon the current one.

A ratio, not a difference, so it means the same thing whether the distribution
is sharp or diffuse. At 1.5 a challenger needs half again the mass of the
focus we are pursuing — enough that a genuine shift crosses it quickly and
turn-to-turn noise never does.
"""


@dataclass
class Commitment:
    """The focus currently being pursued, and what it takes to change it."""

    peak: Position | None = None
    margin: float = SWITCH_MARGIN
    switches: int = 0
    held: int = field(default=0)

    def choose(self, belief: Belief) -> Position | None:
        """Pick a focus to pursue, keeping the current one unless outclassed.

        Returns ``None`` only when belief holds nothing at all. Otherwise the
        answer is stable turn to turn: a rival must carry ``margin`` times the
        mass of the current focus before we move, and a focus that has simply
        drifted a cell is followed rather than abandoned.
        """
        clusters = foci(belief)
        if not clusters:
            self.peak = None
            return None

        current = next((c for c in clusters if self.peak in c.cells), None)
        leader = clusters[0]

        if current is None:
            self.peak = leader.peak
            self.held = 1
            return self.peak

        if leader.peak != current.peak and leader.mass > current.mass * self.margin:
            self.peak = leader.peak
            self.switches += 1
            self.held = 1
            return self.peak

        self.peak = current.peak
        self.held += 1
        return self.peak

    def __str__(self) -> str:
        where = self.peak if self.peak else "nothing"
        return f"committed to {where} for {self.held} turn(s), {self.switches} switch(es)"
